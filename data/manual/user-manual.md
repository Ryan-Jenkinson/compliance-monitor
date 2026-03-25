# Compliance Intelligence Dashboard — User Manual

**Version:** 2026-03-24 build
**Audience:** Compliance team — windows/doors manufacturing
**Scope:** Full operational reference for all dashboard panels, views, and AI-generated content

---

## Table of Contents

1. [Overview](#1-overview)
2. [Navigation & Customization](#2-navigation--customization)
3. [Executive Briefing](#3-executive-briefing)
4. [Topic Intelligence Sections](#4-topic-intelligence-sections)
5. [Compliance Dates & Deadlines](#5-compliance-dates--deadlines)
6. [Legislative Activity](#6-legislative-activity)
7. [Intelligence Maps](#7-intelligence-maps)
8. [Timeline Views](#8-timeline-views)
9. [Director's AI Review](#9-directors-ai-review)
10. [Analytics](#10-analytics)
11. [Resources](#11-resources)

---

## 1. Overview

The Compliance Intelligence Dashboard is a single-page regulatory monitoring interface that aggregates legislative activity, enforcement deadlines, AI-generated analysis, and state-level maps across seven compliance domains relevant to windows/doors manufacturing: PFAS, EPR, REACH, TSCA, Prop 65, Conflict Minerals, and Forced Labor.

It is designed for a small compliance team that monitors regulatory posture across federal and multi-state jurisdictions, tracks bill progression through legislative pipelines, and needs to surface actionable obligations before they become enforcement risks.

The dashboard refreshes on each generation run. All AI-generated content — the Executive Briefing, Director's Review, deadline analysis modals, and bill assessments — is produced at run time based on the article and legislative data ingested for that cycle. Timestamps on each section confirm data currency.

**Primary access:** Open `preview_dashboard_2026-03-24_185508.html` in any modern browser. No login is required for local file access. The file is self-contained.

**Mobile:** The dashboard is responsive. On screens under ~600px, panels stack vertically, the navigation condenses to a hamburger toggle, and topic tabs become horizontally scrollable. All functionality is available on mobile, though the swimlane timeline and state maps are better suited to desktop. (see: `c1-mobile.png`)

---

## 2. Navigation & Customization

### 2.1 Topic Cards

A horizontal strip of eight cards runs across the top of the dashboard. Each card shows:

- **Topic name** — PFAS, EPR, REACH, TSCA, Prop 65, Conflict Minerals, Forced Labor
- **Article count** — number of regulatory updates ingested this run
- **Priority level** — HIGH (red), MED (orange), LOW (green), reflecting the highest urgency item in that topic this cycle
- **NEW badge** — a red numeric badge indicating articles added since the previous run; currently appears on TSCA (2 new) and Prop 65 (2 new)

Clicking any card scrolls the page directly to that topic's section. This is the fastest way to navigate to a specific regulatory domain without using the left sidebar. (see: `c2-nav-cards.png`)

The left sidebar provides the same navigation in list form — Overview, individual regulations, Maps & Data, Timelines, and Archive. The top navigation bar exposes four cross-cutting views: Director Review, Timeline, PFAS Map, and Archive.

### 2.2 Customize Drawer

Click the **Customize** button (gear icon) in the header to open the panel visibility drawer. This drawer lists all eight available dashboard panels organized into three groups:

- **Top Row** — topic cards strip
- **Main Content** — Executive Briefing, topic sections, compliance dates, legislative activity
- **Sidebar** — Regulatory Status heat maps, Bills by Stage, High Relevance States map

Each panel has a teal toggle switch. Click the switch to hide or show that panel. Changes take effect immediately and persist across sessions. To restore the default layout, click **Reset to defaults** at the bottom of the drawer. (see: `c2-drawer.png`)

Use this when preparing a focused review — for example, hiding all sidebar content to give the Executive Briefing and topic sections more readable width, or hiding the briefing entirely if you're drilling into specific deadlines.

---

## 3. Executive Briefing

### What It Is

The Executive Briefing is an AI-generated narrative summary produced at each dashboard run. It synthesizes developments across all seven regulatory topics into a single dated analysis — the current run is stamped **24 Mar 2026**. (see: `c3-exec.png`)

### Structure

The briefing is divided into three collapsible sections:

| Section | Content |
|---|---|
| **Opening** | Situational overview — characterizes the overall regulatory environment for this cycle |
| **Key Developments** | Bulleted list of specific updates, each tagged with context markers identifying implications by topic or operational area |
| **Outlook** | Forward-looking watchpoints — legislation, rulemaking, or enforcement activity expected in the near term |

### How to Use It

Click the triangle icon in the top right of the panel to collapse the entire briefing if you need screen space. Each collapsible section (Opening, Key Developments, Outlook) has its own toggle — expand only the sections relevant to your current task.

The inline tags on Key Developments items are the primary navigation aid within the briefing. Scan these tags to locate entries relevant to your product lines — direct product implications (coatings, seals, glass treatments) versus supply chain implications (substrate suppliers, hardware sourcing) are typically distinguished here.

The briefing does not replace reading individual article cards or deadline entries. Treat it as a triage layer: use it to determine which topic sections and deadline items to examine in detail during a given review cycle. Because it regenerates each run, comparing the Outlook section week-over-week reveals how the regulatory posture is shifting.

---

## 4. Topic Intelligence Sections

### What They Are

Below the Executive Briefing, each of the seven compliance domains has a dedicated section displaying the article cards ingested for that run. These sections are the operational core of the dashboard — each article represents a distinct regulatory development sourced and classified during ingestion. (see: `c4-pfas.png`, `c4-epr.png`)

### Layout

Each topic section contains:

- **Mini-timeline bar** — a horizontal strip of color-coded bars at the top of the section, one bar per article. Red = HIGH urgency, amber = MEDIUM, green = LOW. The bar width and position are consistent; color is the signal.
- **Featured article headline** — the most recent or highest-priority article displays prominently below the timeline bar.
- **Article count badge** — top right of the section header (e.g., "15 UPDATES," "1 UPDATES").
- **Left accent bar** — a colored vertical bar on the article card indicates topic category at a glance.

### Interacting with Articles

**Click any bar** in the mini-timeline to jump to that article and expand its detail view. The detail view includes:

- Full headline and source link
- Impact classification (operational area affected)
- Relevance notes for supply chain vs. direct product

**Click the chevron/triangle** at the bottom of the featured article card to expand additional details without navigating away from the section.

**Source links** in expanded article views open the originating regulatory body's publication, bill text, or agency notice. These are the authoritative references — the dashboard summarizes and classifies; the source link provides the full legal text.

### Priority Logic

Priority levels are assigned per article during ingestion based on jurisdiction scope, implementation timeline, and applicability to windows/doors manufacturing. A topic card showing HIGH means at least one article in that topic section is classified HIGH — it does not mean all articles in that section carry the same weight. Review individual articles to differentiate.

---

## 5. Compliance Dates & Deadlines

### What It Is

The Compliance Dates panel aggregates upcoming regulatory deadlines across all monitored topics and jurisdictions into a single prioritized list. The current build tracks **37 deadlines** in the collapsed default view and **59 deadlines** in the full master timeline. (see: `c5-collapsed.png`)

### Urgency Color Coding

| Color | Priority | Interpretation |
|---|---|---|
| Red | HIGH | Immediate action required; deadline within ~6 months or high penalty exposure |
| Amber | MEDIUM | Planning required; 6–12 months |
| Green | LOW | Monitor; >12 months or lower direct exposure |

### Badges

- **New** (green badge) — deadline added this run; was not present in prior cycle
- **Updated** (amber badge) — an existing deadline's date, scope, or details changed this run

Check these badges first at the start of each review cycle to identify what has changed since your last session.

### Collapsed vs. Expanded List

The default collapsed view shows the 10 most urgent items. Click **Expand** (top right of the panel) to see all 37 items in the scrollable list view. Each entry in the expanded list shows: (see: `c5-expanded.png`)

- Deadline date (left column)
- Regulation name
- Jurisdiction (gray text)
- Compliance category tag (color-coded: PFAS, EPR, TSCA, etc.)
- Brief description of the requirement

### Deadline AI Analysis Modal

Click any deadline entry to open the AI analysis modal for that specific obligation. The modal is structured into five sections: (see: `c5-modal.png`)

| Section | Content |
|---|---|
| **What Is Required** | The regulatory mandate in plain terms |
| **Who Must Comply** | Scope of covered entities — confirms whether your operations are in scope |
| **What We Must Do** | Company-specific enrollment, reporting, or product compliance steps |
| **Company Impact** | Severity badges — HIGH, SUPPLY CHAIN, DIRECT PRODUCTS — and rationale |
| **Penalties for Non-Compliance** | Enforcement actions, fine ranges, business consequences |

At the bottom of the modal, a **90/60/30-day preparation timeline** displays color-coded milestones (red = critical action, orange = standard preparation step). Linked upstream deadlines — for example, PRISM PFAS registration as a prerequisite for a packaging compliance filing — appear here as cross-references.

Use the **Add to Calendar** button at the base of the modal to export the deadline to your calendar application.

The **"+ 27 more"** link surfaces related compliance obligations connected to the same regulatory action — useful for identifying downstream requirements you might otherwise miss.

### Deadline Timeline Widget (Swimlane View)

Within the Compliance Dates panel, a swimlane timeline displays deadlines by topic on horizontal tracks spanning from today to approximately 1,195 days out. (see: `c5-timeline.png`)

- Each dot = one deadline, positioned chronologically
- **Red dot** = HIGH urgency
- **Amber dot** = MEDIUM urgency
- **Topic-colored dot** = LOW urgency
- **Pulsing ring** = newly tracked deadline this run
- **Numbered badge on a dot** (e.g., "3" on PFAS, "8" on EPR) = multiple deadlines sharing the same date; click the badge to see all deadlines in that cluster

Click **Full →** at the end of any swimlane to open the full per-topic timeline view for that regulatory area.

---

## 6. Legislative Activity

### What It Is

The Legislative Activity section tracks active bills across all seven compliance domains, displaying a feed of recent legislative actions with status badges, jurisdictions, and AI-generated bill assessments. The current pipeline contains **729 active bills**.

### Bill Feed

Each entry in the feed shows:

- Date of most recent action
- Action status badge — **ACTION** (blue), **PASSED** (green), **ADVANCED** (teal), **REFERRED** (gray), **AMENDMENT** (orange)
- Bill identifier and jurisdiction
- Brief description of the legislation
- Additional metadata: committee assignment, vote counts, referral details, sponsor notes

### Bill Detail Modal

Click any bill entry to open the AI analysis modal. The modal is organized into six sections: (see: `c6-bill-modal.png`)

| Section | Content |
|---|---|
| **Bill Title & Synopsis** | What the bill does |
| **Current Stage & Next Steps** | Where it is in the legislative process and what triggers advancement |
| **Recent Action Timeline** | Chronological list of actions taken on this bill |
| **Company Impact** | Direct products vs. supply chain exposure, with severity classification |
| **Long-Term Passage Probability** | AI assessment — treat as directional, not deterministic |
| **Recommended Actions** | Specific steps ranked by urgency |

The **MONITORING** tag in the top right of the modal indicates your team is already tracking this bill, preventing duplicate tracking effort.

Click **View on LegiScan / State Legislature** to open the full bill text in the originating legislative database.

### Full-Screen Legislative History

Click the expand icon within the bill feed to open the full-screen legislative activity log. This view displays all tracked actions chronologically across all bills and jurisdictions. (see: `c6-expand.png`)

Use the status badge filters to narrow the view — for example, filter to **PASSED** to see only legislation that has cleared at least one chamber, or **REFERRED** to track early-stage bills entering committee. Press **Escape** or click **Close** to return to the dashboard.

### Bills by Legislative Stage (Sidebar)

The right sidebar displays a **Bills by Legislative Stage** bar chart showing aggregate bill counts at each stage across all topics:

- **Pre Discussion:** 16 bills
- **Committee:** 19 bills
- **Passed One Chamber:** 5 bills

This chart is a macro indicator. A rising Committee count with a flat Passed count suggests legislation is accumulating without advancing — useful for assessing regulatory velocity in any given cycle.

---

## 7. Intelligence Maps

Three interactive maps provide geographic context for regulatory exposure. Access them via the top navigation (**PFAS Map**) or the left sidebar (**Maps & Data**).

### 7.1 PFAS Legislative Watch — State Map

Displays all 51 U.S. states and territories with detected PFAS legislative activity, color-coded by most advanced legislative stage: (see: `c7-pfas-map.png`)

| Color | Stage |
|---|---|
| Gray | Early advocacy / pre-discussion |
| Light tones | Introduced or referred |
| Mid tones | Committee or advanced |
| Green | Enacted |

**Corner dot indicators** on each state tile show data confidence: green = high confidence, amber = medium, gray = low. Prioritize outreach and monitoring actions in states with high-confidence data and advanced legislative stages.

Click any state tile to see:
- Active bills in that state
- Most recent legislative actions
- Engagement guidance for that jurisdiction

Use **Export to Excel** to download the full dataset for integration with internal tracking systems or trade association reporting.

### 7.2 EPR Packaging Law — State Coverage Map

Displays the status of EPR packaging legislation across all U.S. states, classified into four categories: (see: `c7-epr-map.png`)

| Color | Classification |
|---|---|
| Dark blue | Comprehensive Programs |
| Medium blue | Limited Programs (1–2) |
| Light blue | Proposed Legislation |
| Gray | No EPR Programs |

Click any state to view program-specific details: active programs, key dates, and packaging reduction mandates. States with recent activity changes are marked with an amber indicator.

Toggle between **map view** and **Deadline Timeline** view using the control at the top of the panel. The timeline view is the same deadline bar format used in Section 5, filtered to EPR obligations by jurisdiction.

**Download Excel** exports the full state-by-state EPR status dataset.

### 7.3 REACH SVHC — EU Coverage Map

Displays enforcement intensity across EU member states plus Norway, Iceland, Liechtenstein, and Switzerland. Relevant for teams managing SVHC disclosure obligations to EU-based customers or monitoring supplier country-of-origin exposure. (see: `c7-reach-map.png`)

The map uses a four-tier color gradient:

| Shade | Classification |
|---|---|
| Dark green | Priority — highest enforcement intensity and supplier exposure |
| Medium-dark green | Elevated |
| Medium-light green | Moderate |
| Pale green | Standard — full REACH coverage, lower direct relevance |

Click any country to open a detail panel showing:
- Responsible enforcement authority
- Supplier relevance classification
- Country-specific compliance notes

The legend confirms current coverage as EU27 + UK + EEA, as of the generation date. Use this map to prioritize SVHC monitoring by geography and tailor supplier communication by enforcement jurisdiction.

---

## 8. Timeline Views

Full timeline views display per-topic or cross-topic deadline bars on a comprehensive chronological axis. Access them via **Timeline** in the top navigation bar or **Full →** from any swimlane in the Compliance Dates panel.

### 8.1 Per-Topic Timelines

Each topic (PFAS, EPR, REACH, TSCA, etc.) has a dedicated timeline view. The PFAS timeline, for example, covers **15 U.S. jurisdictions** with deadlines plotted from Q3 2026 through Q4 2026 and beyond. (see: `c8-pfas-timeline.png`)

Each entry shows:
- Jurisdiction (left column)
- Requirement description (center)
- Horizontal bar representing time remaining until deadline
- Urgency badge: **High** (red, <6 months), **Medium** (orange, 6–12 months), **Low** (green, >12 months)
- Topic tag linking to detailed source information

Filter by jurisdiction, deadline type, or urgency using the tabs at the top of the timeline view.

The EPR timeline covers **20 deadlines across 10 jurisdictions** organized by region (Federal, California, Colorado, EU, Maine, Maryland). Click any regulation name or **source** link to access detailed requirement information. (see: `c8-epr-timeline.png`)

### 8.2 Master Timeline — All Deadlines

The master timeline consolidates all **59 upcoming deadlines across 18 jurisdictions** on a single view. (see: `c8-all-deadlines.png`)

Jurisdictions run vertically (Federal through state alphabetical order). Deadline bars are positioned chronologically on the horizontal axis. Bar width represents time remaining.

**Color coding in the master timeline:**

| Color | Priority | Time Remaining |
|---|---|---|
| Light pink | HIGH | <6 months |
| Yellow | MEDIUM | 6–12 months |
| Green | LOW | >12 months |

Filter using the topic tabs at the top — MAPS, PFAS, EPR, REACH, TSCA, and others — to isolate deadlines relevant to a specific compliance program. Click any bar to see full deadline details including name, due date, category badge, priority level, and source link.

---

## 9. Director's AI Review

### What It Is

The Director's Review is a separate AI-generated strategic assessment page, accessible via the **Director Review** tab in the top navigation. It evaluates the dashboard's own intelligence quality for a given run — not a compliance status assessment, but a meta-analysis of how useful the current data set is and where it falls short. (see: `c9-director.png`)

### Scored Metrics

Three metrics appear as scored cards at the top:

| Metric | Current Score | What It Measures |
|---|---|---|
| **Usefulness** | 5/10 | Whether the information is relevant and actionable for your specific operations |
| **Actionability** | 3/10 | Whether the dashboard tells you what to do, not just what is happening |
| **Signal/Noise Ratio** | 5/10 | Whether high-priority items are distinguishable from background regulatory activity |

These scores are generated by the AI based on the data ingested for that run. A low Actionability score — as seen here — means the system is detecting regulatory changes but is not surfacing enough context to specify which actions to take first. The narrative below each score explains the specific drivers.

### How to Use It

The Director's Review is organized into three sections:

- **Director's Quote** — a highlighted statement identifying the core limitation of the current run's intelligence
- **What's Working** — bulleted strengths: what the dashboard is correctly triaging, surfacing, or prioritizing this cycle
- **Questions Raised But Not Answered** — gaps the AI has identified in the current data set; examples include missing supplier SVHC data, incomplete deadline tracking for specific jurisdictions, or ambiguous scope determinations for new bills

The questions in the third section are ranked by strategic importance. Use them to direct the next data integration effort or dashboard configuration change. If SVHC supplier data is flagged as missing, that is a prompt to feed that data into the next run rather than an inherent dashboard limitation.

### Cross-State Pattern Analysis

A subordinate section within the Director's Review displays coordinated legislative pattern analysis across states. The current report covers **36 states** with PFAS-related activity. (see: `c9-cross-state.png`)

Each state entry shows:
- Active bill count
- Passage stage (passed_one, advanced)
- Timeline to governor signature or enactment

A **red-highlighted watch list** prioritizes the five states with the most aggressive near-term enforcement posture: Virginia, Maryland, New York, Minnesota, and New Jersey. Each entry includes specific product category restrictions and implementation timelines.

Italicized action items below each state entry provide tactical next steps — auditing specific product lines, engaging trade associations, tracking regulatory guidance. These should be completed before the listed bills reach final passage.

Check the **generated timestamp** (shown as 2026-03-23 in the current build) to confirm data currency before acting on state-level positions.

---

## 10. Analytics

### 10.1 28-Day Article Trend Chart

The trend panel displays article volume over the past 28 days for each monitored compliance topic, rendered as a multi-line chart. (see: `c10-trends.png`)

- Current total volume: **38 articles**
- Each line is color-coded by topic: PFAS (teal), HIGH Urgency (red), TSCA (dark red), and so on
- The right-side legend shows current article counts per category (e.g., 15 for PFAS, 12 for HIGH Urgency items)

Use this chart to detect regulatory spikes — a sudden volume increase in a previously quiet topic area is an early signal that rulemaking, enforcement action, or legislative momentum is accelerating. Flat or declining lines indicate a quieter period for that domain, which may be appropriate for reducing review frequency.

This chart does not show article quality or severity — a spike in article count could be driven by minor state-level notices rather than federal action. Cross-reference volume spikes with the topic section's priority indicators before escalating.

### 10.2 Bill Pipeline Funnel

The bill pipeline displays **729 active bills** organized by topic and legislative stage in a stacked bar visualization. (see: `c10-funnel.png`)

Topics covered: Conflict Minerals, EPR, Forced Labor, PFAS, Prop 65, TSCA.

Stages displayed left to right:

| Stage | Badge Color |
|---|---|
| Introduced | Gray |
| Committee | Blue |
| Passed | Orange |
| Advanced | Red |

The bar length represents total bill volume per topic. The stage distribution shows where legislation is concentrating or stalling. PFAS carries the highest volume (375 total bills) with significant committee concentration — indicating active legislative attention without broad enactment yet.

Click the expand icon on any topic row to drill into individual bills for that topic, or filter by stage to isolate the most advanced legislation across all topics. The funnel is most useful for tracking attrition — how many bills enter committee versus how many advance — which informs passage probability assessments in individual bill modals.

---

## 11. Resources

### Regulatory Glossary

The glossary is accessible via the left sidebar or bottom of the dashboard. It contains **86 regulatory terms** organized by category. (see: `c10-glossary.png`)

Categories include: Chemicals, US Federal, EU Regulation, State Agency, and 16 others. Each entry includes:
- Abbreviated term (left column)
- Full formal definition
- Practical context explaining applicability to your industry
- Last update date

**Search** the glossary using the search bar at the top to locate specific terms. **Filter by category tag** to narrow to a regulatory domain — for example, clicking **US Federal** isolates TSCA, CERCLA, CAA, and related federal statutes.

Color-coded tags indicate regulatory domain: blue = US Federal, teal = chemical classifications. This is auto-generated content — verify definitions against primary regulatory sources for formal compliance determinations.

### Calendar Export

Deadline entries throughout the dashboard — in the Compliance Dates panel and in individual deadline AI analysis modals — include an **Add to Calendar** button. This exports the deadline date, obligation description, and jurisdiction to a standard calendar file compatible with Outlook, Google Calendar, and Apple Calendar.

Export individual deadlines from their AI analysis modals, or use the bulk export options in the expanded deadline list to push multiple deadlines at once. The exported event includes the compliance category, priority level, and source link in the event notes field.

---

## Appendix: Quick Reference — Color Coding

| Color | Context | Meaning |
|---|---|---|
| Red | Priority badges | HIGH urgency / <6 months |
| Amber/Orange | Priority badges | MEDIUM urgency / 6–12 months |
| Green | Priority badges | LOW urgency / >12 months |
| Red (badge) | Topic card NEW badge | New articles added this run |
| Teal | Toggle switches | Panel enabled |
| Blue | Bill status | ACTION — recent legislative action |
| Green | Bill status | PASSED |
| Teal | Bill status | ADVANCED |
| Gray | Bill status | REFERRED |
| Orange | Bill status | AMENDMENT |
| Dark green | REACH map | Priority enforcement jurisdiction |
| Pale green | REACH map | Standard coverage jurisdiction |
| Dark blue | EPR map | Comprehensive program enacted |
| Gray | EPR map | No EPR program |

---

## Appendix: Known Limitations

- **AI-generated content is run-specific.** Executive Briefing, Director's Review, bill assessments, and deadline analysis modals reflect the data ingested at generation time. Content does not update between runs.
- **Passage probability assessments** in bill modals are directional AI estimates. Do not use them as the sole basis for compliance investment decisions.
- **Data confidence indicators** on the PFAS state map (corner dots) signal ingestion quality, not regulatory certainty. Low-confidence states may have incomplete bill tracking.
- **The Director's Review scores** evaluate dashboard intelligence quality, not your company's compliance status. A Usefulness score of 5/10 reflects data completeness at that run — it is an input to improving the next run, not a compliance health metric.
- **Source links** open external legislative databases and agency websites. Link validity depends on those sites remaining accessible; archived versions are not stored within the dashboard file.