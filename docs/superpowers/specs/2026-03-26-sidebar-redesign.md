# Sidebar Navigation Redesign

**Date:** 2026-03-26
**Status:** Approved
**File:** `dashboard/templates/dashboard.html`

## Summary

Replace the current flat nav rail with a collapsible accordion sidebar. Function-first grouping (Option B structure), colored Lucide icons per group (Option D style). All accordion state persists in localStorage.

---

## Groups & Behavior

### Always-visible (no accordion)

| Item | Icon | Color | Action |
|------|------|-------|--------|
| Overview | `layout-dashboard` | `#0F766E` teal | Scroll to `section-dashboard` |

---

### Accordion groups

All group headers are clickable to expand/collapse. State saved to localStorage key `sidebarAccordion`.

#### 1. Dashboards
- **Icon:** `layers` · **Color:** `#0D9488`
- **Default:** Open
- **Sub-items:** PFAS · EPR · REACH · TSCA · Prop 65 · Conflict Minerals · Forced Labor
- **Behavior:** Each opens the topic deep-dive page (`/{topic}.html`) in a new tab

#### 2. News & Articles
- **Icon:** `newspaper` · **Color:** `#60A5FA`
- **Default:** Open
- **Sub-items:** PFAS · EPR · REACH · TSCA · Prop 65 · Conflict Minerals · Forced Labor
- **Behavior:** Click scrolls to that topic's article section on the current page **and** expands it if collapsed. Each topic section in the dashboard has a data attribute (`data-topic`) and an expand toggle button with class `section-expand-btn`. The sidebar click handler calls `scrollToSection(id)` then triggers `.click()` on that button if the section does not already have class `expanded`.

#### 3. Deadlines
- **Icon:** `triangle-alert` · **Color:** `#D97706`
- **Default:** Collapsed
- **Sub-items:** All Deadlines · PFAS · EPR · REACH · TSCA · Regulatory Calendar
- **Behavior:** "All Deadlines" scrolls to `section-deadlines`; topic sub-items scroll to deadlines and apply a topic filter; "Regulatory Calendar" scrolls to `section-calendar`

#### 4. Maps
- **Icon:** `globe` · **Color:** `#7C3AED`
- **Default:** Collapsed
- **Sub-items:** PFAS State Map · PFAS Intel Map · EPR Map · REACH Map
- **Behavior:** All open external GitHub Pages URL in new tab

#### 5. Timelines
- **Icon:** `gantt-chart` · **Color:** `#0369A1`
- **Default:** Collapsed
- **Sub-items:** All Topics · PFAS · EPR · REACH · TSCA
- **Behavior:** All open external GitHub Pages timeline URL in new tab

#### 6. Legislative
- **Icon:** `landmark` · **Color:** `#BE185D`
- **Default:** Collapsed
- **Sub-items:** Bill Activity · Cross-State Intel · Changes Today
- **Behavior:** All scroll to their section on the current page (`section-leg-activity`, `section-cross-state`, `section-changes`)

#### 7. Downloads & Archive
- **Icon:** `archive` · **Color:** `#4B5563`
- **Default:** Collapsed
- **Sub-items:** PFAS Tracker (.xlsx) · EPR Tracker (.xlsx) · REACH Tracker (.xlsx) · Calendar (.ics) · Archive
- **Behavior:** XLSX + .ics trigger download/open; Archive scrolls to `section-archive`

---

### Special pinned items (below divider, no accordion)

| Item | Icon | Color | Style | Action |
|------|------|-------|-------|--------|
| Glossary | `book-open` | `#92400E` → `#FBBF24` on hover | Amber | Opens `glossary.html` in new tab |
| Director Review | `eye` | `#6B5A85` → `#C084FC` on hover | Purple | Opens `director_review.html` in new tab |

---

## Visual Design

- **Icons:** Lucide icon set. Add `<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>` to the `<head>` of `dashboard.html` (not currently present). Call `lucide.createIcons()` at the end of the existing DOMContentLoaded block.
- **Icon size:** 16×16px on group headers, same on pinned items
- **Sub-item dots:** 5×5px colored `border-radius: 50%` spans matching topic color (no icon on sub-items)
- **Group header active state:** When a group's section is in view, the group header gets `color: #E4E7ED` and `border-left: 3px solid` matching the group's icon color
- **Sub-item hover:** `color: #C0C8D8`, `background: rgba(255,255,255,0.03)`
- **Chevron:** Rotates 90° when open via CSS `transform: rotate(90deg)` on `.open` class

---

## Collapsed Rail (icon-only mode)

Existing 56px collapsed mode is preserved. When `body.sidebar-collapsed`:
- All group labels, sub-items, and special item labels hide (opacity 0, existing behavior)
- Only the 16px colored icons remain visible as click targets
- Clicking an icon in collapsed mode expands the rail first, then opens that group

---

## Active State Tracking

The existing `updateActiveRailLink()` scroll watcher is extended:
- It now highlights the **group header** (not a flat link) when any of its target sections is in view
- Groups with external links only (Maps, Timelines) are excluded from scroll tracking
- The Overview flat link remains the fallback active item when at the top

---

## localStorage Keys

| Key | Value | Purpose |
|-----|-------|---------|
| `sidebarCollapsed` | `'0'` / `'1'` | Existing — rail width collapse |
| `sidebarAccordion` | JSON object `{ "dashboards": true, "news": true, ... }` | Per-group open/closed state |

---

## What is removed

- All existing flat `.rail-link` items except Overview are replaced by accordion groups
- The standalone "All Timelines", "Leg. Activity", "Calendar", "Changes", "Glossary", "Archive" flat links in the current nav are removed and folded into their respective groups
- The `.rail-divider` between topic links and other links is replaced by the new group structure

---

## Out of scope

- Mobile hamburger menu behavior (unchanged)
- Right-side panel collapse (`toggleSidebarPanel`) (unchanged)
- Any change to section content or layout outside the rail nav
