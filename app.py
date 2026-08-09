from __future__ import annotations

import html
import logging
import os
from collections.abc import Mapping, Sequence

import streamlit as st

from tariff_app.app_content import (
    DISCLOSURE_COPY,
    DISCLOSURE_DETAILS,
    action_presentation,
    impact_outlook_story,
    partition_policy_notices,
)
from tariff_app.db import DatabaseConfigurationError, get_connection_pool
from tariff_app.embeddings import EmbeddingService
from tariff_app.identity import IdentityError, actor_email, forwarded_email
from tariff_app.models import PolicyNoticeSnapshot
from tariff_app.navigation import request_navigation, resolve_route
from tariff_app.outlook import ImpactOutlookSnapshot
from tariff_app.repository import RecordNotFound, TariffRepository
from tariff_app.sourcing_review import RetryableReviewWriteFailure
from tariff_app.sourcing_review_repository import SourcingReviewRepository
from tariff_app.workflow import TariffWorkflow

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Tariff Exposure Copilot",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      :root {
        --ink: #17221e;
        --muted: #5d6a65;
        --line: #dce4df;
        --paper: #f6f8f5;
        --green: #0c6b4f;
        --green-dark: #074a38;
        --gold: #e7b858;
      }
      .stApp { background: var(--paper); }
      [data-testid="stAppViewContainer"] { color: var(--ink); }
      [data-testid="stAppViewContainer"] h1,
      [data-testid="stAppViewContainer"] h2,
      [data-testid="stAppViewContainer"] h3,
      [data-testid="stAppViewContainer"] p { color: var(--ink); }
      .tariff-hero {
        padding: 1.3rem 1.5rem;
        border-radius: 18px;
        color: white;
        background: linear-gradient(125deg, #102820, #194b39 72%, #6f6232);
        margin-bottom: .8rem;
        box-shadow: 0 12px 30px rgba(16, 42, 67, .16);
      }
      .tariff-hero h1 { margin: 0; font-size: clamp(1.7rem, 4vw, 2.35rem); }
      .tariff-hero h1, .tariff-hero p { color: white !important; }
      .tariff-hero p { margin: .35rem 0 0; color: #d7e3de !important; }
      .impact-hero {
        padding: clamp(1.4rem, 4vw, 2.4rem);
        border-radius: 20px;
        color: white;
        background: linear-gradient(125deg, #102820 0%, #194b39 70%, #6f6232 150%);
        box-shadow: 0 14px 42px rgba(20, 39, 31, .14);
        margin: .8rem 0 1.2rem;
      }
      .impact-hero .eyebrow { color: #f3d891; font-size: .75rem; font-weight: 800; }
      .impact-hero h1 {
        color: white !important;
        margin: .45rem 0 .7rem;
        max-width: 60rem;
        font: 700 clamp(1.8rem, 4vw, 3.05rem)/1.06 Georgia, serif;
      }
      .impact-hero p { color: #d7e3de !important; margin: 0; font-size: 1.05rem; }
      .featured-card {
        padding: 1.25rem;
        border: 1px solid #dccb96;
        border-radius: 16px;
        background: linear-gradient(120deg, #fffdf6, #fff7dd);
        margin-bottom: .8rem;
      }
      .featured-card h3 { margin: .45rem 0; }
      .eyebrow {
        color: var(--green);
        font-size: .75rem;
        font-weight: 800;
        letter-spacing: .08em;
        text-transform: uppercase;
      }
      .breadcrumb { color: var(--muted); font-size: .85rem; margin-bottom: .35rem; }
      .action-priority {
        display: inline-block;
        padding: .2rem .55rem;
        border-radius: 999px;
        color: white;
        background: var(--green);
        font-size: .75rem;
        font-weight: 800;
      }
      div[data-testid="stMetric"] {
        background: white;
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: .8rem 1rem;
      }
      div[data-testid="stMetric"] * { color: var(--ink) !important; }
      div[data-testid="stButton"] button { min-height: 2.65rem; }
      @media (max-width: 700px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; }
        .impact-hero { border-radius: 14px; }
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        div[data-testid="column"] {
          flex: 1 1 13rem !important;
          width: auto !important;
          min-width: min(100%, 13rem);
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def repository() -> TariffRepository:
    repo = TariffRepository(get_connection_pool())
    repo.verify_runtime_schema()
    return repo


def forwarded_headers() -> dict[str, str]:
    try:
        return dict(st.context.headers)
    except (AttributeError, RuntimeError):
        return {}


def navigate(view: str, **identifiers: int) -> None:
    request_navigation(st.session_state, view, **identifiers)
    st.rerun()


def clear_review_draft() -> None:
    for key in (
        "sourcing_review_selection",
        "sourcing_review_confirmation",
        "sourcing_review_failure",
    ):
        st.session_state.pop(key, None)


def render_app_chrome(*, actor: str, active_view: str) -> None:
    st.markdown(
        """
        <section class="tariff-hero">
          <h1>Tariff &amp; Trade-Policy Exposure Copilot</h1>
          <p>Policy evidence, purchased-component exposure, and the next sourcing decision.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    with st.expander(DISCLOSURE_COPY, expanded=False):
        st.markdown(DISCLOSURE_DETAILS)

    inbox_nav, reviews_nav, identity = st.columns([1, 1, 3])
    if inbox_nav.button(
        "Policy Inbox",
        use_container_width=True,
        type="primary" if active_view in {"inbox", "outlook"} else "secondary",
    ):
        navigate("inbox")
    if reviews_nav.button(
        "Sourcing Reviews",
        use_container_width=True,
        type="primary" if active_view in {"reviews", "review"} else "secondary",
    ):
        navigate("reviews")
    identity.caption(f"Signed-in Strategic Sourcing Manager: {actor}")
    st.divider()


def notice_label(notice: PolicyNoticeSnapshot) -> str:
    published = notice.publication_date.isoformat() if notice.publication_date else "Date unavailable"
    return f"{notice.source_identifier} · {notice.agency} · {published}"


def run_analysis(
    workflow: TariffWorkflow, notice: PolicyNoticeSnapshot, *, reanalysis: bool = False
) -> None:
    failure_key = f"analysis_failure_{notice.notice_id}"
    try:
        outlook = workflow.analyze_policy_notice(
            notice.notice_id,
            embedding_service=EmbeddingService(),
            reanalysis=reanalysis,
        )
    except ValueError as error:
        st.session_state[failure_key] = str(error)
        st.rerun()
    except Exception:
        logger.exception("Impact Outlook analysis failed")
        st.session_state[failure_key] = (
            "The evidence-backed analysis failed. No partial Impact Outlook was published."
        )
        st.rerun()
    else:
        st.session_state.pop(failure_key, None)
        navigate("outlook", notice_id=notice.notice_id, outlook_id=outlook.outlook_id)


def render_analysis_control(
    workflow: TariffWorkflow,
    notice: PolicyNoticeSnapshot,
    *,
    label: str,
    use_container_width: bool = True,
) -> None:
    failure = st.session_state.get(f"analysis_failure_{notice.notice_id}")
    if failure:
        st.error(f"Analysis failed — {failure}")
        st.caption(
            "Processing failure is not No Actionable Exposure Identified. The failed attempt "
            "published no partial Outlook."
        )
        label = "Retry evidence-backed analysis"
    if st.button(label, key=f"analyze_{notice.notice_id}", use_container_width=use_container_width):
        run_analysis(workflow, notice)


def render_policy_inbox(workflow: TariffWorkflow) -> None:
    notices = workflow.policy_inbox()
    sections = partition_policy_notices(notices)
    st.markdown('<p class="eyebrow">Step 1 · Triage</p>', unsafe_allow_html=True)
    st.title("Policy Inbox")
    st.write(
        "Select a persisted Policy Notice Snapshot. The featured historical replay and current "
        "policy activity use the same evidence-backed analysis path."
    )

    st.subheader("Featured Demonstration Notice")
    st.caption("Historical replay · intentionally separate from current policy activity")
    if not sections.featured:
        st.info("The Featured Demonstration Notice has not been persisted yet.")
    for notice in sections.featured:
        st.markdown(
            '<section class="featured-card"><span class="eyebrow">Featured historical replay</span>'
            f"<h3>{html.escape(notice.title)}</h3>"
            f"<p>{html.escape(notice_label(notice))}</p>"
            "<p>A pinned real notice that demonstrates direct exposure, validation uncertainty, "
            "deduplicated spend, Recommended Actions, and a confirmed durable write.</p></section>",
            unsafe_allow_html=True,
        )
        outlook = workflow.impact_outlook(notice.notice_id)
        if outlook is None:
            render_analysis_control(workflow, notice, label="Run demonstration")
        elif st.button(
            "Open persisted Impact Outlook",
            key=f"open_featured_outlook_{notice.notice_id}",
            use_container_width=True,
            type="primary",
        ):
            navigate("outlook", notice_id=notice.notice_id, outlook_id=outlook.outlook_id)

    st.divider()
    st.subheader("Current Policy Inbox")
    st.caption("Live Policy Notice Snapshots ordered by publication date")
    if not sections.current:
        st.info("No current policy notices have been ingested yet.")
    for notice in sections.current:
        with st.container(border=True):
            st.markdown(f"**{notice.title}**")
            st.caption(notice_label(notice))
            outlook = workflow.impact_outlook(notice.notice_id)
            if outlook is not None:
                st.write(f"Analysis result: **{outlook.outlook_status}**")
                if st.button(
                    "Open persisted Impact Outlook",
                    key=f"open_current_outlook_{notice.notice_id}",
                ):
                    navigate(
                        "outlook",
                        notice_id=notice.notice_id,
                        outlook_id=outlook.outlook_id,
                    )
            else:
                st.write("Analysis result: **Not analyzed**")
                render_analysis_control(
                    workflow,
                    notice,
                    label="Analyze notice",
                    use_container_width=False,
                )

    with st.expander("Search cited policy evidence"):
        render_policy_evidence_search(workflow)
    with st.expander("Technical validation tools"):
        scenario_tab, lakebase_tab = st.tabs(["Scenario context", "Lakebase persistence"])
        with scenario_tab:
            render_exposure_context(workflow)
        with lakebase_tab:
            render_foundation_diagnostics(workflow)


def render_policy_evidence_search(workflow: TariffWorkflow) -> None:
    query = st.text_input(
        "Search policy evidence",
        key="policy_evidence_query",
        placeholder="Which Section 301 duty applies to covered imports?",
    )
    if not st.button("Search cited policy evidence", key="policy_evidence_search"):
        return
    try:
        results = workflow.search_policy_evidence(query, embedding_service=EmbeddingService())
    except ValueError as error:
        st.info(str(error))
        return
    except Exception:
        logger.exception("Policy evidence search failed")
        st.error("Policy evidence search is temporarily unavailable. Check the App logs and retry.")
        return
    if not results:
        st.info("No cited policy evidence matched that query.")
    for result in results:
        st.markdown(f"**{html.escape(result.citation)}**")
        st.caption(f"Semantic similarity: {result.similarity:.0%}")
        st.write(result.chunk_text)
        st.markdown(f"[Open source notice]({result.canonical_url})")


def render_exposure_context(workflow: TariffWorkflow) -> None:
    components = workflow.scenario_components()
    if not components:
        st.info("The Demonstration Scenario has no Components available yet.")
        return
    labels = {
        f"{component.name} ({component.component_key})": component.component_key
        for component in components
    }
    selected_label = st.selectbox("Component", list(labels), key="scenario_component")
    contexts = workflow.retrieve_exposure_context([labels[selected_label]])
    if not contexts:
        st.warning("No bounded exposure context was found for the selected Component.")
        return
    context = contexts[0]
    st.caption(
        f"Component provenance: {context.component_provenance.label}. Supplier, origin, spend, "
        "BOM, and classification records below are synthetic Demonstration Scenario data."
    )
    st.dataframe(
        [
            {
                "Product line": product_line.name,
                "Segment": product_line.segment_name,
                "Public provenance": product_line.provenance.source_citation,
            }
            for product_line in context.product_lines
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.dataframe(
        [
            {
                "Supplier (Synthetic)": relationship.supplier_name,
                "Origin (Synthetic)": relationship.origin_name,
                "Annual Spend (Synthetic)": f"${relationship.annual_spend:,.0f}",
                "Measurement period": relationship.measurement_period,
                "Relationship": relationship.supply_relationship_key,
            }
            for relationship in context.supply_relationships
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_foundation_diagnostics(workflow: TariffWorkflow) -> None:
    st.caption("Write a diagnostic through the app, then reload to verify durable Lakebase access.")
    with st.form("diagnostic_form", clear_on_submit=True):
        message = st.text_area(
            "Diagnostic message",
            max_chars=2_000,
            placeholder="Lakebase foundation is reachable.",
        )
        submitted = st.form_submit_button("Record diagnostic", use_container_width=True)
    if submitted:
        try:
            workflow.record_diagnostic(message)
            st.success("Diagnostic saved. Reload the app to verify it remains visible.")
        except ValueError as error:
            st.error(str(error))
        except Exception:
            logger.exception("Diagnostic write failed")
            st.error("Could not save the diagnostic record. Check the Databricks App logs.")
    records = workflow.list_diagnostics()
    if not records:
        st.info("No foundation diagnostics have been recorded yet.")
    for record in records:
        created_at = record.created_at.isoformat() if record.created_at else "pending"
        st.write(f"**{record.actor_email}** · {created_at}")
        st.caption(record.message)


def render_outlook_page(
    workflow: TariffWorkflow,
    notice: PolicyNoticeSnapshot,
    outlook: ImpactOutlookSnapshot,
    *,
    actor: str,
) -> None:
    back, spacer = st.columns([1, 4])
    if back.button("← Policy Inbox", use_container_width=True):
        navigate("inbox")
    spacer.markdown(
        f'<p class="breadcrumb">Policy Inbox › {html.escape(notice.source_identifier)} › '
        f"Impact Outlook IO-{outlook.outlook_id}</p>",
        unsafe_allow_html=True,
    )

    story = impact_outlook_story(outlook, is_featured=notice.is_featured)
    st.markdown(
        '<section class="impact-hero"><span class="eyebrow">Executive impact brief · '
        f"{html.escape(outlook.outlook_status)}</span>"
        f"<h1>{html.escape(story.headline)}</h1>"
        f"<p>{html.escape(story.uncertainty)}</p></section>",
        unsafe_allow_html=True,
    )

    metrics = st.columns(4)
    metrics[0].metric("Annual Spend Exposed", f"${outlook.annual_spend_exposed:,.0f}")
    metrics[1].metric(
        "Spend Requiring Validation", f"${outlook.spend_requiring_validation:,.0f}"
    )
    metrics[2].metric("Affected product lines", outlook.affected_product_line_count)
    metrics[3].metric(
        "Impact Window",
        outlook.impact_window_start.isoformat() if outlook.impact_window_start else "Validate",
    )
    st.caption(outlook.impact_window_label)
    st.caption(
        "Annual Spend Exposed is modeled purchase spend, deduplicated by Supply Relationship. "
        "It is not an expected cost increase."
    )

    st.subheader("Exposure evidence")
    if not outlook.findings:
        st.info(
            "No Actionable Exposure Identified: the policy scope was assessed and produced no "
            "credible Impact Findings or Recommended Actions."
        )
    for finding in outlook.findings:
        with st.expander(f"{finding.product_line_name} — {finding.segment_name}", expanded=True):
            st.caption(
                f"Product-line view: ${finding.annual_spend_exposed:,.0f} exposed; "
                f"${finding.spend_requiring_validation:,.0f} requiring validation. Shared spend "
                "is counted once in the Outlook total."
            )
            for bundle in finding.evidence_bundles:
                st.markdown(f"**{bundle.component_name} · {bundle.match_confidence}**")
                st.caption(
                    f"{bundle.supplier_name} · {bundle.origin_name} · "
                    f"${bundle.annual_spend:,.0f} · {bundle.measurement_period}"
                )
                st.write(bundle.reasoning)
                st.write(f"Uncertainty: {bundle.uncertainty}")
                st.caption(f"Scenario path: {bundle.scenario_path}")
                st.markdown(f"**Policy evidence:** {bundle.policy_evidence.citation}")
                st.write(bundle.policy_evidence.chunk_text)
                st.markdown(f"**HTS scope evidence:** {bundle.hts_scope_evidence.citation}")
                st.caption("Covered HTSUS headings: " + ", ".join(bundle.hts_scope_evidence.hts_codes))
                st.markdown(f"[Open policy source]({bundle.policy_evidence.canonical_url})")

    render_outlook_history(workflow, notice, outlook)

    st.subheader("Recommended Actions")
    st.caption("Prioritized, full-width responses supported by this immutable Outlook evidence.")
    if not outlook.recommended_actions:
        st.info("No Recommended Actions are justified by this completed Outlook.")
    for action in outlook.recommended_actions:
        presentation = action_presentation(action, outlook.findings)
        with st.container(border=True):
            conditional = " · Conditional" if action.is_conditional else ""
            st.markdown(
                f'<span class="action-priority">Priority {action.priority}</span> {conditional}',
                unsafe_allow_html=True,
            )
            st.markdown(f"### {action.title}")
            st.write(presentation.rationale)
            st.caption(
                "Supported findings: "
                + (", ".join(presentation.supported_findings) or "Persisted evidence scope")
            )
            st.caption("Evidence relationships: " + ", ".join(action.evidence_relationship_keys))
            if st.button(
                "Open Sourcing Review",
                key=f"open_sourcing_review_{outlook.outlook_id}_{action.action_key}",
            ):
                st.session_state["sourcing_review_selection"] = {
                    "outlook_id": outlook.outlook_id,
                    "action_key": action.action_key,
                    "action_title": action.title,
                }
                st.session_state.pop("sourcing_review_confirmation", None)
                st.session_state.pop("sourcing_review_failure", None)
                st.rerun()

    render_sourcing_review_confirmation(workflow, actor=actor)


def render_outlook_history(
    workflow: TariffWorkflow,
    notice: PolicyNoticeSnapshot,
    outlook: ImpactOutlookSnapshot,
) -> None:
    history = workflow.impact_outlook_history(notice.notice_id)
    with st.expander("Analysis & Action History", expanded=True):
        st.caption(
            "Opening an entry reads that immutable snapshot. It does not rerun analysis or alter "
            "its evidence."
        )
        for item in history:
            label = f"IO-{item.outlook_id} · sequence {item.reanalysis_sequence} · {item.outlook_status}"
            if item.outlook_id == outlook.outlook_id:
                st.markdown(f"**{label} · Viewing**")
            elif st.button(label, key=f"history_outlook_{item.outlook_id}"):
                navigate("outlook", notice_id=notice.notice_id, outlook_id=item.outlook_id)
        if st.button(
            "Create linked reanalysis successor",
            key=f"reanalyze_{notice.notice_id}_{outlook.outlook_id}",
        ):
            run_analysis(workflow, notice, reanalysis=True)


def render_sourcing_review_confirmation(workflow: TariffWorkflow, *, actor: str) -> None:
    selection = st.session_state.get("sourcing_review_selection")
    if not selection:
        return
    st.divider()
    st.subheader("Confirm Sourcing Review")
    confirmation = st.session_state.get("sourcing_review_confirmation")
    if confirmation is None:
        st.caption(
            "Objective and owner are editable. The source recommendation and evidence scope are "
            "read-only and will be bound to the confirmation."
        )
        try:
            draft = workflow.sourcing_review_draft(
                source_outlook_id=selection["outlook_id"],
                action_key=selection["action_key"],
            )
        except Exception:
            logger.exception("Sourcing Review draft could not be loaded")
            st.error("The stored recommendation and evidence scope could not be loaded.")
            return
        st.write(f"**Source recommendation (read-only):** {draft.recommendation}")
        st.dataframe(
            [
                {
                    "Product line": link.product_line_name,
                    "Component": link.component_name,
                    "Supplier": link.supplier_name,
                    "Match Confidence": link.match_confidence,
                    "Uncertainty": link.uncertainty,
                }
                for link in draft.scope_links
            ],
            use_container_width=True,
            hide_index=True,
        )
        with st.form("prepare_sourcing_review_confirmation"):
            objective = st.text_input(
                "Objective",
                value=f"Investigate: {selection['action_title']}",
                max_chars=2_000,
            )
            owner_email = st.text_input("Owner", value=actor, max_chars=320)
            prepare = st.form_submit_button(
                "Review exact confirmation payload", use_container_width=True
            )
        if st.button("Cancel", key="cancel_sourcing_review_draft"):
            clear_review_draft()
            st.rerun()
        if not prepare:
            return
        try:
            confirmation = workflow.prepare_sourcing_review_confirmation(
                source_outlook_id=selection["outlook_id"],
                action_key=selection["action_key"],
                objective=objective,
                owner_email=owner_email,
            )
        except ValueError as error:
            st.error(str(error))
            return
        except Exception:
            logger.exception("Sourcing Review confirmation preparation failed")
            st.error("The exact confirmation payload could not be prepared. No Review was created.")
            return
        st.session_state["sourcing_review_confirmation"] = confirmation

    payload = confirmation.reviewed_payload()
    st.write(f"**Recommendation (read-only):** {payload['recommendation']}")
    st.write(f"**Objective:** {payload['objective']}")
    st.write(f"**Owner:** {payload['owner_email']}")
    st.write(f"**Initial status:** {payload['initial_status']}")
    st.caption(f"Source Impact Outlook Snapshot: IO-{payload['source_outlook_id']}")
    st.dataframe(
        [
            {
                "Product line": link["product_line_name"],
                "Component": link["component_name"],
                "Supplier": link["supplier_name"],
                "Match Confidence": link["match_confidence"],
                "Uncertainty": link["uncertainty"],
            }
            for link in payload["scope_links"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    failure = st.session_state.get("sourcing_review_failure")
    if failure is not None:
        st.error(failure.message)
        st.caption(
            "No Sourcing Review was created. The objective, owner, recommendation, and evidence "
            "scope above are preserved unchanged."
        )
        retry, cancel = st.columns(2)
        if retry.button("Retry unchanged write", use_container_width=True, type="primary"):
            try:
                retry_confirmation = workflow.retry_sourcing_review_confirmation(
                    failed_agent_run_id=failure.failed_agent_run_id
                )
                result = workflow.confirm_sourcing_review(retry_confirmation)
            except Exception:
                logger.exception("Sourcing Review unchanged write retry failed")
                st.error("The unchanged write could not be retried safely.")
            else:
                if isinstance(result, RetryableReviewWriteFailure):
                    st.session_state["sourcing_review_confirmation"] = retry_confirmation
                    st.session_state["sourcing_review_failure"] = result
                    st.rerun()
                clear_review_draft()
                navigate("review", review_id=result.review.review_id)
        if cancel.button("Cancel", use_container_width=True):
            clear_review_draft()
            st.rerun()
        return

    confirm, edit, cancel = st.columns(3)
    if confirm.button(
        "Confirm and open Sourcing Review", use_container_width=True, type="primary"
    ):
        try:
            result = workflow.confirm_sourcing_review(confirmation)
        except ValueError as error:
            st.error(str(error))
            return
        except Exception:
            logger.exception("Sourcing Review confirmation failed")
            st.error("The confirmed write failed safely. No partial Review was published.")
            return
        if isinstance(result, RetryableReviewWriteFailure):
            st.session_state["sourcing_review_failure"] = result
            st.rerun()
        clear_review_draft()
        navigate("review", review_id=result.review.review_id)
    if edit.button("Edit objective or owner", use_container_width=True):
        try:
            workflow.decline_sourcing_review(confirmation)
        except Exception:
            logger.exception("Superseded Sourcing Review confirmation could not be recorded")
            st.error("The existing confirmation could not be replaced safely.")
            return
        st.session_state.pop("sourcing_review_confirmation", None)
        st.rerun()
    if cancel.button("Cancel", key="cancel_sourcing_review_confirmation", use_container_width=True):
        try:
            workflow.decline_sourcing_review(confirmation)
        except Exception:
            logger.exception("Sourcing Review cancellation could not be recorded")
            st.error("The confirmation decision could not be recorded.")
            return
        clear_review_draft()
        st.info("Sourcing Review confirmation cancelled. No Review was created.")


def render_sourcing_reviews_index(workflow: TariffWorkflow) -> None:
    st.markdown('<p class="eyebrow">Read-only workflow records</p>', unsafe_allow_html=True)
    st.title("Sourcing Reviews")
    st.write("Durable investigations created from explicitly confirmed Recommended Actions.")
    reviews = workflow.sourcing_reviews()
    if not reviews:
        st.info("No Sourcing Reviews have been opened yet.")
        if st.button("Return to Policy Inbox"):
            navigate("inbox")
        return
    for review in reviews:
        with st.container(border=True):
            st.markdown(f"### SR-{review.review_id} · {review.status}")
            st.write(f"**Objective:** {review.objective}")
            st.write(f"**Owner:** {review.owner_email}")
            st.caption(f"Source Impact Outlook: IO-{review.source_outlook_id}")
            if st.button(
                f"Open SR-{review.review_id}",
                key=f"open_review_{review.review_id}",
            ):
                navigate("review", review_id=review.review_id)


def render_sourcing_review_detail(workflow: TariffWorkflow, review_id: int) -> None:
    review = workflow.sourcing_review(review_id)
    reviews_link, outlook_link, spacer = st.columns([1, 1, 3])
    if reviews_link.button("← Sourcing Reviews", use_container_width=True):
        navigate("reviews")
    if outlook_link.button("Source Outlook", use_container_width=True):
        navigate(
            "outlook",
            notice_id=review.source_notice_id,
            outlook_id=review.source_outlook_id,
        )
    spacer.markdown(
        f'<p class="breadcrumb">Sourcing Reviews › SR-{review.review_id} · Source IO-'
        f"{review.source_outlook_id}</p>",
        unsafe_allow_html=True,
    )
    st.markdown('<p class="eyebrow">Step 3 · Act</p>', unsafe_allow_html=True)
    st.title(f"Sourcing Review SR-{review.review_id}")
    st.success(f"{review.status} · durable confirmed write")
    st.write(f"**Objective:** {review.objective}")
    st.write(f"**Owner:** {review.owner_email}")
    st.write(f"**Source recommendation:** {review.recommendation}")
    st.caption(f"Fixed evidence scope: {review.evidence_scope_hash}")
    st.subheader("Evidence scope")
    st.dataframe(
        [
            {
                "Product line": link.product_line_name,
                "Component": link.component_name,
                "Supplier": link.supplier_name,
                "Match Confidence": link.match_confidence,
                "Uncertainty": link.uncertainty,
            }
            for link in review.scope_links
        ],
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Audit history", expanded=True):
        st.write(
            f"Opened by {review.created_by_email} at {review.created_at.isoformat()} from confirmed "
            f"Recommended Action `{review.action_key}` on IO-{review.source_outlook_id}."
        )


def _route_int(route: Mapping[str, str], name: str) -> int | None:
    raw_value = route.get(name)
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _notice_by_id(
    notices: Sequence[PolicyNoticeSnapshot], notice_id: int
) -> PolicyNoticeSnapshot | None:
    return next((notice for notice in notices if notice.notice_id == notice_id), None)


def run_app() -> None:
    try:
        repo = repository()
    except DatabaseConfigurationError as error:
        st.error(str(error))
        st.info("Attach the Lakebase resource and set ENDPOINT_NAME before deploying.")
        st.stop()
    except Exception:
        logger.exception("Lakebase initialization failed")
        st.error("Lakebase is temporarily unavailable. Check the Databricks App logs and try again.")
        st.stop()

    headers = forwarded_headers()
    forwarded_actor = forwarded_email(headers)
    local_identity = os.getenv("LOCAL_USER_EMAIL", "")
    if not forwarded_actor:
        local_identity = st.sidebar.text_input(
            "Local development identity",
            value=local_identity,
            placeholder="you@example.com",
            help="Databricks supplies the signed-in email automatically after deployment.",
        )
    try:
        actor = actor_email(headers, local_identity)
    except IdentityError as error:
        st.warning(str(error))
        st.info("Set LOCAL_USER_EMAIL locally or type an identity in the sidebar to continue.")
        st.stop()

    workflow = TariffWorkflow(
        repo,
        actor_email=actor,
        sourcing_review_store=SourcingReviewRepository(get_connection_pool()),
    )
    route = resolve_route(st.session_state, st.query_params)
    legacy_review_id = _route_int(route, "review_id")
    view = route.get("view", "review" if legacy_review_id else "inbox")
    if view not in {"inbox", "outlook", "reviews", "review"}:
        view = "inbox"
    render_app_chrome(actor=actor, active_view=view)

    try:
        if view == "reviews":
            render_sourcing_reviews_index(workflow)
            return
        if view == "review":
            review_id = _route_int(route, "review_id") or legacy_review_id
            if review_id is None:
                st.error("The Sourcing Review link is invalid.")
                return
            render_sourcing_review_detail(workflow, review_id)
            return
        if view == "outlook":
            notice_id = _route_int(route, "notice_id")
            outlook_id = _route_int(route, "outlook_id")
            if notice_id is None or outlook_id is None:
                st.error("The Impact Outlook link is invalid.")
                return
            notice = _notice_by_id(workflow.policy_inbox(), notice_id)
            if notice is None:
                raise RecordNotFound(f"Policy Notice Snapshot {notice_id} does not exist.")
            outlook = workflow.impact_outlook_snapshot(outlook_id)
            if outlook.notice_id != notice.notice_id:
                raise RecordNotFound("The Impact Outlook does not belong to this Policy Notice.")
            render_outlook_page(workflow, notice, outlook, actor=actor)
            return
        render_policy_inbox(workflow)
    except RecordNotFound as error:
        st.error(str(error))
    except Exception:
        logger.exception("Application surface could not be loaded")
        st.error("This application surface could not be loaded. Retry from the Policy Inbox.")


run_app()
