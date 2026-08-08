# Tariff Exposure Management

The domain of identifying purchased-component exposure created by trade-policy changes and initiating a sourcing response to protect manufacturing margin.

## Language

**Policy Inbox**:
The queue of newly ingested trade-policy notices available for a Strategic Sourcing Manager to assess. It is the workflow entry point, not a general news feed.
_Avoid_: Dashboard, alerts feed

**Strategic Sourcing Manager**:
The operating user accountable for evaluating input-cost exposure and initiating an appropriate sourcing response. Executives are consumers of the resulting story and evidence, not the application's primary operators.
_Avoid_: Buyer, procurement user, executive user

**Sourcing Review**:
A durable, assigned investigation opened from one Recommended Action to resolve an exposed purchased component or material uncertainty; it may cover multiple product lines that share the same exposure. Opening one is the MVP agent's only operational write and requires separate user confirmation, while analytical snapshots and audit records are persisted automatically.
_Avoid_: Ticket, task

**Impact Outlook**:
One consolidated, evidence-backed analysis for a single policy notice. It summarizes aggregate exposure and contains an Impact Finding for each affected product line, while reporting exposed spend and uncertainty rather than claiming a precise COGS increase without sufficient evidence.
_Avoid_: Exposure report, cost forecast

**Policy Notice Snapshot**:
An immutable, point-in-time copy of the exact policy source analyzed, identified by its source document, retrieval time, canonical location, and content fingerprint. Live and featured notices use the same snapshot concept.
_Avoid_: Cached notice, demo fixture

**Impact Outlook Snapshot**:
An immutable, point-in-time record of a completed Impact Outlook, including its findings, evidence, spend measures, recommendations, and the notice, enterprise-data, classification-schedule, and analysis versions that produced it. Reanalysis creates a linked successor rather than changing or silently recalculating an existing snapshot.
_Avoid_: Current calculation, recommendation cache

**Impact Finding**:
The product-line-level part of an Impact Outlook that identifies matched components and supplier categories, exposed spend, timing, supporting evidence, Match Confidence, and recommended sourcing actions.
_Avoid_: Separate outlook, alert

**Impact Window**:
The policy-supported period in which exposure may begin, derived from the notice's effective date or effective period. It does not predict when a supplier will change prices; an absent or uncertain effective date is marked as requiring validation.
_Avoid_: Supplier increase date, price forecast period

**Demonstration Scenario**:
The synthetic but plausible enterprise layer containing component relationships, suppliers, countries of origin, and spend. It is clearly distinguished from public evidence and must not be presented as Mueller Water Products' actual procurement data.
_Avoid_: Sample data, Mueller supplier data

**Public Enterprise Backbone**:
The cited company, segment, and product-line facts that use Mueller Water Products as an illustrative public anchor for the Demonstration Scenario. It excludes all modeled procurement relationships and currently spans Water Flow Solutions–Specialty Valves plus Water Management Solutions–Repair Products and Fire Hydrants; the scenario is not a representation of Mueller's actual operations beyond those cited facts.
_Avoid_: Mueller procurement model, public BOM, Mueller case study

**Component**:
A modeled item purchased at the illustrative company's procurement boundary that exists once in the Demonstration Scenario and may contribute to more than one product line. Its procurement exposure is represented through Supply Relationships; the MVP does not model the Supplier's internal material recipe.
_Avoid_: Product-line component, raw-material mention

**BOM Relationship**:
The modeled association between a product line and a Component. It may carry an evidence-backed spend-allocation share, but absent that evidence the spend remains explicitly shared and unallocated; the relationship never independently owns procurement spend.
_Avoid_: BOM component, spend record

**Supply Relationship**:
The unique modeled association of a Component, supplier, country of origin, and measurement-period Annual Spend. It is the deduplication grain for exposure totals.
_Avoid_: Supplier record, BOM spend

**Supplier**:
A fictional organization in the Demonstration Scenario from which one or more Components are modeled as purchased. Its name and relationship to Mueller Water Products are illustrative and never presented as public fact.
_Avoid_: Mueller supplier, vendor

**Country of Origin**:
The modeled country where a Component in a Supply Relationship is produced for tariff-scope analysis. It is not the Supplier's headquarters or shipping location and makes no claim about Mueller Water Products' actual sourcing footprint.
_Avoid_: Supplier country, ship-from country

**Classification Assertion**:
An evidence-backed statement that a Component or supplier-specific variant belongs to an HTS code for a jurisdiction and schedule period. A Component may have validated, candidate, or superseded assertions; a Supply Relationship identifies which assertion applies when the sourced variant controls classification.
_Avoid_: Component HTS field, permanent HTS code

**Supplier Input Exposure**:
Possible upstream cost pressure when a Supplier uses a tariff-affected material to produce a purchased Component whose own import classification is not directly matched. It may support a Likely match when the input path is evidenced or Needs validation when it is not, but it is not a Direct match and its structured multi-tier composition is outside the MVP.
_Avoid_: Direct component exposure, confirmed pass-through

**Demonstration Notice Set**:
Two pinned, real Federal Register notices analyzed through the same path as live Policy Inbox notices: one Featured Demonstration Notice guaranteed to exercise meaningful exposure and one negative notice guaranteed to exercise No Actionable Exposure Identified. It is a reproducibility aid, not a separate demo engine or synthetic policy corpus.
_Avoid_: Demo mode, fake notice, scenario engine

**Featured Demonstration Notice**:
The real historical policy notice in the Demonstration Notice Set whose modeled classifications and origins intentionally produce a multi-product-line Impact Outlook. Its featured status and historical-replay context are disclosed in the Policy Inbox so it cannot be mistaken for a current notice.
_Avoid_: Sample alert, fake policy

**Match Confidence**:
A transparent evidence classification attached to an asserted policy-to-component relationship: **Direct match**, **Likely match**, or **Needs validation**. A Direct match has aligned policy scope text, an applicable validated Classification Assertion, and applicable origin with no known conflict; a Likely match has a supported indirect path such as evidenced Supplier Input Exposure but unresolved pass-through; Needs validation has missing, ambiguous, or conflicting evidence. The classification expresses evidence strength, not legal certainty or financial impact.
_Avoid_: Risk score, AI confidence score

**Annual Spend Exposed**:
The modeled annual purchase spend associated with unique Supply Relationships that directly or likely match a policy notice's scope. It states its measurement period and Demonstration Scenario provenance, is deduplicated in Outlook totals, excludes Spend Requiring Validation, and is not an expected cost increase.
_Avoid_: Cost impact, tariff cost, spend increase

**Spend Requiring Validation**:
The modeled annual purchase spend associated with unique Supply Relationships whose policy exposure cannot yet be established because classification, origin, or other required evidence is ambiguous or missing. It is displayed separately from Annual Spend Exposed and is never silently included in an exposed-spend total.
_Avoid_: Potential exposure total, unconfirmed spend, Annual Spend Exposed

**Evidence Bundle**:
The minimum support for an Impact Finding: a cited policy passage, HTS classification evidence, the Demonstration Scenario path from product line through component and supplier/origin to spend, and a short explanation of the connection and remaining uncertainty. A finding without cited policy evidence is excluded from an Impact Outlook.
_Avoid_: Sources, references

**Recommended Action**:
One evidence-linked sourcing response selected from the approved playbook: validate classification or origin, request supplier confirmation or a quote, evaluate alternate sourcing, review inventory or pre-buy feasibility, or assess product pricing. An Impact Outlook presents at most three prioritized actions and never pads the list when fewer actions are justified; opening a Sourcing Review is the workflow operation for tracking an action, not an action itself.
_Avoid_: AI advice, suggestion

**No Actionable Exposure Identified**:
An assessed Impact Outlook outcome with no credible Impact Findings, no Annual Spend Exposed, and no Recommended Actions. It records that the policy scope was evaluated rather than indicating a failed or incomplete analysis.
_Avoid_: No impact, clean

**Outlook Status**:
The workflow classification of an Impact Outlook: **Action recommended**, **Validation required**, or **No actionable exposure identified**. Validation required still presents useful recommendations, but leads with the missing evidence, marks dependent actions as conditional, and states the risk of an incorrect assumption.
_Avoid_: Severity, risk rating

**Processing State**:
The lifecycle state of an Impact Outlook analysis: **Queued**, **Analyzing**, **Complete**, or **Failed**. Outlook Status exists only for a Complete analysis; Failed processing is retryable and must never be represented as No actionable exposure identified.
_Avoid_: Outlook status, impact status

**Agent Run**:
An append-only audit record for one agent analysis or operational-write attempt, linking its actor, timestamps, versioned inputs and tools, structured events, outcome, and any retry predecessor. It references immutable snapshots and retains evidence-backed explanations but excludes hidden model reasoning.
_Avoid_: Chat history, chain of thought, application log
