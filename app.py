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

    workflow = TariffWorkflow(repo, actor_email=actor)

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
