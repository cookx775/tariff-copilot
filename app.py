from __future__ import annotations

import html
import logging
import os

import streamlit as st

from tariff_app.app_content import DISCLOSURE_COPY, DISCLOSURE_DETAILS
from tariff_app.db import DatabaseConfigurationError, get_connection_pool
from tariff_app.embeddings import EmbeddingService
from tariff_app.identity import IdentityError, actor_email, forwarded_email
from tariff_app.repository import TariffRepository
from tariff_app.sourcing_review import RetryableReviewWriteFailure
from tariff_app.sourcing_review_repository import SourcingReviewRepository
from tariff_app.workflow import TariffWorkflow

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


st.set_page_config(
    page_title="Tariff Exposure Copilot",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .stApp { background: #f6f8fb; }
      [data-testid="stAppViewContainer"] { color: #111827; }
      [data-testid="stAppViewContainer"] h1,
      [data-testid="stAppViewContainer"] h2,
      [data-testid="stAppViewContainer"] h3,
      [data-testid="stAppViewContainer"] p { color: #111827; }
      [data-testid="stSidebar"] { background: #102a43; }
      [data-testid="stSidebar"] * { color: #f9fafb; }
      .tariff-hero {
        padding: 1.4rem 1.6rem;
        border-radius: 18px;
        color: white;
        background: linear-gradient(125deg, #102a43, #1363df 72%, #36c5f0);
        margin-bottom: 1rem;
        box-shadow: 0 12px 30px rgba(16, 42, 67, .18);
      }
      .tariff-hero h1 { margin: 0; font-size: 2rem; }
      .tariff-hero h1, .tariff-hero p { color: white !important; }
      .tariff-hero p { margin: .35rem 0 0; opacity: .9; }
      .diagnostic-card {
        background: white;
        border: 1px solid #e5e7eb;
        border-left: 4px solid #1363df;
        border-radius: 12px;
        margin: .55rem 0;
        padding: .8rem 1rem;
      }
      .diagnostic-meta { color: #64748b; font-size: .8rem; margin-bottom: .35rem; }
      div[data-testid="stMetric"] {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: .8rem 1rem;
      }
      div[data-testid="stMetric"] * { color: #111827 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def repository() -> TariffRepository:
    repo = TariffRepository(get_connection_pool())
    repo.initialize()
    return repo


def forwarded_headers() -> dict[str, str]:
    try:
        return dict(st.context.headers)
    except (AttributeError, RuntimeError):
        return {}


def render_diagnostics(workflow: TariffWorkflow) -> None:
    records = workflow.list_diagnostics()
    if not records:
        st.info("No foundation diagnostics have been recorded yet.")
        return

    for record in records:
        created_at = (
            record.created_at.strftime("%Y-%m-%d %H:%M UTC") if record.created_at else "pending"
        )
        st.markdown(
            "<div class='diagnostic-card'><div class='diagnostic-meta'>"
            f"{html.escape(record.actor_email)} · {created_at}</div>"
            f"{html.escape(record.message)}</div>",
            unsafe_allow_html=True,
        )


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
        f"Component provenance: {context.component_provenance.label}. "
        "All supplier, origin, spend, BOM, and classification records below are Synthetic "
        "Demonstration Scenario data."
    )
    st.markdown("**Public Enterprise Backbone**")
    st.dataframe(
        [
            {
                "Segment (Public source)": product_line.segment_name,
                "Product line (Public source)": product_line.name,
                "Provenance": product_line.provenance.source_citation,
            }
            for product_line in context.product_lines
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("**Supply Relationships**")
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
    st.caption(
        "Annual Spend is stored once per unique Supply Relationship. A shared Component can "
        "appear under multiple product lines without copying this spend."
    )

    st.markdown("**Classification Assertions (Synthetic)**")
    st.dataframe(
        [
            {
                "State": assertion.state,
                "Sourced variant": assertion.sourced_variant,
                "Jurisdiction": assertion.jurisdiction,
                "Schedule period": assertion.schedule_period,
                "HTS code": assertion.hts_code,
            }
            for assertion in context.classification_assertions
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_policy_evidence_search(workflow: TariffWorkflow) -> None:
    query = st.text_input(
        "Search policy evidence",
        key="policy_evidence_query",
        placeholder="Which Section 301 duty applies to covered imports?",
    )
    if not st.button("Search cited policy evidence", key="policy_evidence_search"):
        return
    try:
        results = workflow.search_policy_evidence(
            query,
            embedding_service=EmbeddingService(),
        )
    except ValueError as error:
        st.info(str(error))
        return
    except Exception:
        logger.exception("Policy evidence search failed")
        st.error("Policy evidence search is temporarily unavailable. Check the App logs and retry.")
        return

    if not results:
        st.info("No cited policy evidence matched that query.")
        return
    for result in results:
        st.markdown(f"**{html.escape(result.citation)}**")
        st.caption(f"Semantic similarity: {result.similarity:.0%}")
        st.write(result.chunk_text)
        st.markdown(f"[Open source notice]({result.canonical_url})")


def render_impact_outlook(outlook, workflow: TariffWorkflow, *, actor: str) -> None:
    """Render a persisted result only; all analysis remains behind the workflow facade."""
    st.markdown("### Impact Outlook")
    st.caption(
        "Immutable analysis snapshot. Annual Spend Exposed is modeled purchase spend, not an "
        "expected cost increase."
    )
    st.markdown("#### Impact brief")
    st.write(outlook.executive_brief)
    st.caption(outlook.impact_window_label)
    st.caption(f"Impact Window evidence: {outlook.impact_window_policy_evidence.citation}")

    st.markdown("#### Decision metrics")
    metrics = st.columns(3)
    metrics[0].metric("Annual Spend Exposed", f"${outlook.annual_spend_exposed:,.0f}")
    metrics[1].metric("Spend Requiring Validation", f"${outlook.spend_requiring_validation:,.0f}")
    metrics[2].metric("Affected product lines", outlook.affected_product_line_count)
    st.caption(f"Outlook Status: {outlook.outlook_status}")

    st.markdown("#### Evidence and Impact Findings")
    for finding in outlook.findings:
        with st.expander(f"{finding.product_line_name} — {finding.segment_name}", expanded=True):
            st.caption(
                f"Product-line view: ${finding.annual_spend_exposed:,.0f} exposed; "
                f"${finding.spend_requiring_validation:,.0f} requiring validation. "
                "Shared Supply Relationship spend is deduplicated in the Outlook total."
            )
            for bundle in finding.evidence_bundles:
                st.markdown(f"**{bundle.component_name} · {bundle.match_confidence}**")
                st.caption(
                    f"Synthetic relationship: {bundle.supplier_name} · {bundle.origin_name} · "
                    f"${bundle.annual_spend:,.0f} · {bundle.measurement_period}"
                )
                st.markdown(f"**Policy evidence:** {bundle.policy_evidence.citation}")
                st.write(bundle.policy_evidence.chunk_text)
                st.markdown(f"**HTS scope evidence:** {bundle.hts_scope_evidence.citation}")
                st.caption(
                    "Exact covered HTSUS headings: "
                    + ", ".join(bundle.hts_scope_evidence.hts_codes)
                )
                st.write(bundle.hts_scope_evidence.scope_text)
                st.caption(
                    "HTS evidence: "
                    + ", ".join(
                        (
                            f"{item.hts_code} ({item.state}; {item.sourced_variant}; "
                            f"{item.jurisdiction}; {item.schedule_period}) — "
                            f"{item.provenance.source_citation}"
                        )
                        for item in bundle.classification_evidence
                    )
                )
                st.caption(f"Scenario path: {bundle.scenario_path}")
                st.write(f"Reasoning: {bundle.reasoning}")
                st.write(f"Uncertainty: {bundle.uncertainty}")
                st.markdown(f"[Open policy source]({bundle.policy_evidence.canonical_url})")

    st.divider()
    st.markdown("#### Recommended Actions")
    if not outlook.recommended_actions:
        st.info("No Recommended Actions are justified by this completed Outlook.")
        return
    for action in outlook.recommended_actions:
        conditional = " — conditional" if action.is_conditional else ""
        st.markdown(f"**{action.priority}. {action.title}{conditional}**")
        st.caption("Evidence scope: " + ", ".join(action.evidence_relationship_keys))
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

    render_sourcing_review_confirmation(workflow, actor=actor)


def render_sourcing_review_confirmation(workflow: TariffWorkflow, *, actor: str) -> None:
    selection = st.session_state.get("sourcing_review_selection")
    if not selection:
        return
    st.divider()
    st.markdown("#### Confirm Sourcing Review")
    confirmation = st.session_state.get("sourcing_review_confirmation")
    if confirmation is None:
        with st.form("prepare_sourcing_review_confirmation"):
            objective = st.text_input(
                "Objective",
                value=f"Investigate: {selection['action_title']}",
                max_chars=2_000,
            )
            owner_email = st.text_input("Owner", value=actor, max_chars=320)
            prepare = st.form_submit_button("Review exact confirmation payload")
        if st.button("Cancel", key="cancel_sourcing_review_draft"):
            st.session_state.pop("sourcing_review_selection", None)
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
            st.session_state["sourcing_review_confirmation"] = confirmation
        except ValueError as error:
            st.error(str(error))
            return
        except Exception:
            logger.exception("Sourcing Review confirmation preparation failed")
            st.error("The exact confirmation payload could not be prepared. No Review was created.")
            return

    payload = confirmation.reviewed_payload()
    st.write(f"**Recommendation:** {payload['recommendation']}")
    st.write(f"**Objective:** {payload['objective']}")
    st.write(f"**Owner:** {payload['owner_email']}")
    st.write(f"**Initial status:** {payload['initial_status']}")
    st.caption(f"Source Impact Outlook Snapshot: {payload['source_outlook_id']}")
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
    confirm_col, decline_col = st.columns(2)
    if confirm_col.button("Confirm and open Sourcing Review", use_container_width=True):
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
            st.error(result.message)
        else:
            st.session_state.pop("sourcing_review_selection", None)
            st.session_state.pop("sourcing_review_confirmation", None)
            st.query_params["review_id"] = str(result.review.review_id)
            st.rerun()
    if decline_col.button("Decline", use_container_width=True):
        try:
            workflow.decline_sourcing_review(confirmation)
        except Exception:
            logger.exception("Sourcing Review decline failed")
            st.error("The confirmation decision could not be recorded.")
            return
        st.session_state.pop("sourcing_review_selection", None)
        st.session_state.pop("sourcing_review_confirmation", None)
        st.info("Sourcing Review confirmation declined. No Review was created.")

    failure = st.session_state.get("sourcing_review_failure")
    if failure is not None and st.button("Retry unchanged write"):
        try:
            st.session_state["sourcing_review_confirmation"] = (
                workflow.retry_sourcing_review_confirmation(
                    failed_agent_run_id=failure.failed_agent_run_id
                )
            )
            st.session_state.pop("sourcing_review_failure", None)
            st.rerun()
        except Exception:
            logger.exception("Sourcing Review retry preparation failed")
            st.error("A fresh approval for the unchanged payload could not be prepared.")


def render_sourcing_review_detail(workflow: TariffWorkflow, review_id: int) -> None:
    review = workflow.sourcing_review(review_id)
    st.markdown("### Sourcing Review")
    st.caption(f"Durable Review {review.review_id} · {review.status}")
    st.write(f"**Recommendation:** {review.recommendation}")
    st.write(f"**Objective:** {review.objective}")
    st.write(f"**Owner:** {review.owner_email}")
    st.caption(f"Source Impact Outlook Snapshot: {review.source_outlook_id}")
    if review.scope_links:
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
    if st.button("Back to Policy Inbox"):
        st.query_params.clear()
        st.rerun()


def render_featured_outlook(workflow: TariffWorkflow, notices, *, actor: str) -> None:
    featured = [notice for notice in notices if notice.is_featured]
    if not featured:
        st.info("The Featured Demonstration Notice has not been persisted yet.")
        return
    labels = {
        f"{notice.source_identifier} — {notice.title}": notice.notice_id for notice in featured
    }
    selected_label = st.selectbox(
        "Featured Demonstration Notice", list(labels), key="featured_demonstration_notice"
    )
    selected_notice_id = labels[selected_label]
    outlook = workflow.impact_outlook(selected_notice_id)
    if outlook is None and st.button("Generate Impact Outlook", use_container_width=True):
        try:
            workflow.analyze_policy_notice(
                selected_notice_id,
                embedding_service=EmbeddingService(),
            )
            st.success("Complete immutable Impact Outlook Snapshot is ready.")
        except ValueError as error:
            st.error(str(error))
        except Exception:
            logger.exception("Impact Outlook analysis failed")
            st.error("Impact Outlook analysis failed. No partial snapshot was published.")

    outlook = workflow.impact_outlook(selected_notice_id)
    if outlook is not None:
        render_impact_outlook(outlook, workflow, actor=actor)


def run_app() -> None:
    try:
        repo = repository()
    except DatabaseConfigurationError as error:
        st.error(str(error))
        st.info("Attach the Lakebase resource and set ENDPOINT_NAME before deploying.")
        st.stop()
    except Exception:
        logger.exception("Lakebase initialization failed")
        st.error(
            "Lakebase is temporarily unavailable. Check the Databricks App logs and try again."
        )
        st.stop()

    headers = forwarded_headers()
    forwarded_actor = forwarded_email(headers)
    local_identity = os.getenv("LOCAL_USER_EMAIL", "")

    st.sidebar.markdown("## Application identity")
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

    review_id = st.query_params.get("review_id")
    if review_id:
        try:
            render_sourcing_review_detail(workflow, int(review_id))
        except (TypeError, ValueError):
            st.error("The Sourcing Review link is invalid.")
        except Exception:
            logger.exception("Sourcing Review detail could not be loaded")
            st.error("The Sourcing Review could not be loaded.")
        return

    st.markdown(
        """
        <section class="tariff-hero">
          <h1>Tariff &amp; Trade-Policy Exposure Copilot</h1>
          <p>Connect policy evidence to purchased-component exposure and the next sourcing decision.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    with st.expander(DISCLOSURE_COPY, expanded=False):
        st.markdown(DISCLOSURE_DETAILS)
    st.caption(f"Signed-in actor: {actor}")

    notices = workflow.policy_inbox()
    metric = st.columns(2)
    metric[0].metric("Policy Inbox", len(notices))
    metric[1].metric("Foundation diagnostics", len(workflow.list_diagnostics()))

    st.markdown("### Policy Inbox")
    if notices:
        st.dataframe(
            [
                {
                    "Source": notice.source_identifier,
                    "Title": notice.title,
                    "Agency": notice.agency,
                    "Published": notice.publication_date,
                    "Analysis state": notice.analysis_state.replace("_", " ").title(),
                    "Featured": "Historical replay" if notice.is_featured else "Current",
                }
                for notice in notices
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("The Policy Inbox is ready for the first Federal Register notice.")

    st.markdown("### Featured Demonstration Notice")
    st.caption(
        "Historical replay using the same persisted Policy Notice Snapshot, semantic evidence, "
        "and Demonstration Scenario contracts as live analysis."
    )
    render_featured_outlook(workflow, notices, actor=actor)

    st.markdown("### Sourcing Reviews")
    try:
        reviews = workflow.sourcing_reviews()
    except Exception:
        logger.exception("Sourcing Review index could not be loaded")
        st.info("Sourcing Reviews are temporarily unavailable.")
    else:
        if not reviews:
            st.info("No Sourcing Reviews have been opened yet.")
        for review in reviews:
            if st.button(
                f"{review.objective} — {review.status}",
                key=f"sourcing_review_{review.review_id}",
            ):
                st.query_params["review_id"] = str(review.review_id)
                st.rerun()

    st.markdown("### Search cited policy evidence")
    st.caption("Semantic search retrieves passages from immutable Policy Notice Snapshots.")
    render_policy_evidence_search(workflow)

    st.markdown("### Demonstration Scenario")
    st.caption(
        "Retrieve only the selected Component's bounded product-line, supplier, origin, "
        "classification, spend, and provenance context."
    )
    render_exposure_context(workflow)

    st.markdown("### Lakebase foundation check")
    st.caption(
        "Write a diagnostic record through the application, then reload to verify durable access."
    )
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
            st.success("Diagnostic record saved. Reload the app to verify it remains visible.")
        except ValueError as error:
            st.error(str(error))
        except Exception:
            logger.exception("Diagnostic write failed")
            st.error("Could not save the diagnostic record. Check the Databricks App logs.")

    st.markdown("### Recent foundation diagnostics")
    render_diagnostics(workflow)


run_app()
