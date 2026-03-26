# Sidebar Navigation Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat nav rail in `dashboard/templates/dashboard.html` with a collapsible accordion sidebar using Lucide icons, function-first grouping, and localStorage-persisted accordion state.

**Architecture:** All changes are self-contained in a single file — `dashboard/templates/dashboard.html`. The work splits into four areas: (1) add the Lucide CDN script, (2) add new accordion CSS, (3) replace the rail-nav HTML block, (4) replace/extend the sidebar JavaScript. No Python files change. The existing `expandTopic()` JS function is reused as-is for News clicks.

**Tech Stack:** Jinja2 HTML template, vanilla JS, CSS, Lucide icon library (CDN)

---

## File Map

| Area | Lines (approx) | What changes |
|------|---------------|--------------|
| `<head>` | 9 | Add Lucide `<script>` tag |
| Rail CSS | 71–191 | Add accordion CSS classes after existing rail styles |
| Collapsed-state CSS | 88–96 | Extend to hide `.rail-sub` and `.rail-group-label` when collapsed |
| Rail HTML | 2082–2157 | Replace `<div class="rail-nav">` content; keep `rail-footer` |
| Sidebar JS | 3374–3430 | Replace `updateActiveRailLink()`; add accordion toggle + localStorage |
| End of last `<script>` | 4880 | Call `lucide.createIcons()` |

---

## Task 1: Add Lucide CDN script

**Files:**
- Modify: `dashboard/templates/dashboard.html` (~line 9)

- [ ] **Step 1: Add Lucide script tag to `<head>`**

Find this line (line 9):
```html
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans...&display=swap" rel="stylesheet">
```

Add immediately after it:
```html
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
```

- [ ] **Step 2: Call `lucide.createIcons()` after all DOM content**

Find the very last `</script>` tag before `</body>` (currently line 4880). Add `lucide.createIcons();` as the last line inside that script block, before `</script>`:

```html
<script>
  function csDashTabShow(topic) {
    document.querySelectorAll('.cs-dash-panel').forEach(function(el) { el.classList.remove('active'); });
    document.querySelectorAll('.cs-dash-tab').forEach(function(el) { el.classList.remove('active'); });
    var panel = document.querySelector('.cs-dash-panel[data-cs-panel="' + topic + '"]');
    var tab = document.querySelector('.cs-dash-tab[data-cs-topic="' + topic + '"]');
    if (panel) panel.classList.add('active');
    if (tab) tab.classList.add('active');
  }
  lucide.createIcons();
</script>
```

- [ ] **Step 3: Verify Lucide loads**

Open `data/preview_dashboard.html` in a browser (run `python run.py --preview` first if stale). Open DevTools console. Run:
```js
lucide
```
Expected: the lucide object is defined (not `undefined`).

- [ ] **Step 4: Commit**
```bash
git add dashboard/templates/dashboard.html
git commit -m "feat(sidebar): add Lucide icon library CDN"
```

---

## Task 2: Add accordion CSS

**Files:**
- Modify: `dashboard/templates/dashboard.html` (after line ~191, inside the `<style>` block)

- [ ] **Step 1: Add accordion CSS after the existing `.rail-footer-text` block**

Find this comment (line ~193):
```css
    /* ============================================================
       TOP BAR
```

Insert the following CSS block immediately before that comment:

```css
    /* ── Rail accordion groups ── */
    .rail-group-header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 14px 8px 16px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-inverse-dim);
      border-left: 3px solid transparent;
      cursor: pointer;
      white-space: nowrap;
      user-select: none;
      transition: color 0.12s, background 0.12s;
    }
    .rail-group-header:hover { color: var(--text-inverse); background: var(--surface-dark-2); }
    .rail-group-header.active { color: var(--text-inverse); }
    .rail-group-label { transition: opacity 0.15s; white-space: nowrap; flex: 1; min-width: 0; overflow: hidden; }
    .rail-group-chevron {
      font-size: 9px;
      opacity: 0.35;
      transition: transform 0.15s, opacity 0.15s;
      flex-shrink: 0;
      margin-left: auto;
    }
    .rail-group-header.open .rail-group-chevron { transform: rotate(90deg); opacity: 0.7; }

    .rail-group-sub {
      overflow: hidden;
      max-height: 0;
      transition: max-height 0.2s ease;
    }
    .rail-group-sub.open { max-height: 400px; }

    .rail-sub-link {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 5px 14px 5px 38px;
      font-size: 11.5px;
      font-weight: 400;
      color: #5A6374;
      cursor: pointer;
      white-space: nowrap;
      border-left: 3px solid transparent;
      text-decoration: none;
      transition: color 0.1s, background 0.1s;
    }
    .rail-sub-link:hover { color: #C0C8D8; background: rgba(255,255,255,0.03); text-decoration: none; }

    .rail-sub-dot {
      width: 5px; height: 5px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    /* Special pinned items: Glossary (amber) and Director Review (purple) */
    .rail-link-amber {
      display: flex; align-items: center; gap: 10px;
      padding: 8px 14px 8px 16px;
      font-size: 12px; font-weight: 500;
      color: #7A6640;
      border-left: 3px solid transparent;
      text-decoration: none;
      white-space: nowrap;
      transition: color 0.12s, background 0.12s;
    }
    .rail-link-amber:hover { color: #FBBF24; background: rgba(217,119,6,0.06); text-decoration: none; }

    .rail-link-purple {
      display: flex; align-items: center; gap: 10px;
      padding: 8px 14px 8px 16px;
      font-size: 12px; font-weight: 500;
      color: #6B5A85;
      border-left: 3px solid transparent;
      text-decoration: none;
      white-space: nowrap;
      transition: color 0.12s, background 0.12s;
    }
    .rail-link-purple:hover { color: #C084FC; background: rgba(192,132,252,0.06); text-decoration: none; }

    /* Collapsed rail: hide labels, sub-items */
    body.sidebar-collapsed .rail-group-sub { max-height: 0 !important; }
    body.sidebar-collapsed .rail-group-label { opacity: 0; }
    body.sidebar-collapsed .rail-group-chevron { opacity: 0; }
    body.sidebar-collapsed .rail-link-amber .rail-label { opacity: 0; }
    body.sidebar-collapsed .rail-link-purple .rail-label { opacity: 0; }
```

- [ ] **Step 2: Commit**
```bash
git add dashboard/templates/dashboard.html
git commit -m "feat(sidebar): add accordion CSS classes"
```

---

## Task 3: Replace rail-nav HTML

**Files:**
- Modify: `dashboard/templates/dashboard.html` (lines 2088–2156)

This is the largest step. Replace everything between `<div class="rail-nav">` and its closing `</div>` (just before `<div class="rail-footer">`), keeping the `rail-footer` block untouched.

- [ ] **Step 1: Replace the entire `<div class="rail-nav">` block**

Find (starting line 2088):
```html
  <div class="rail-nav">
    <a class="rail-link active" data-target="section-dashboard" onclick="scrollToSection('section-dashboard')">
      ...
    {% if timelines %}
    ...
    {% endif %}
  </div>
```

Replace with:

```html
  <div class="rail-nav">

    <!-- ── Always-visible flat links ── -->
    <div style="padding:6px 0 4px;">
      <a class="rail-link active" id="rail-overview" data-target="section-dashboard" onclick="scrollToSection('section-dashboard')">
        <i data-lucide="layout-dashboard" style="width:16px;height:16px;color:#0F766E;flex-shrink:0;"></i>
        <span class="rail-label">Overview</span>
      </a>
      <a class="rail-link" id="rail-calendar-pin" data-target="section-calendar" onclick="scrollToSection('section-calendar')">
        <i data-lucide="calendar" style="width:16px;height:16px;color:#D97706;flex-shrink:0;"></i>
        <span class="rail-label">Reg. Calendar</span>
      </a>
    </div>

    <div class="rail-divider"></div>

    <!-- ── 1. Dashboards ── -->
    <div class="rail-group-header" id="rail-grp-dashboards" data-group="dashboards" onclick="toggleRailGroup('dashboards', event)">
      <i data-lucide="layers" style="width:16px;height:16px;color:#0D9488;flex-shrink:0;"></i>
      <span class="rail-group-label">Dashboards</span>
      <span class="rail-group-chevron">&#9654;</span>
    </div>
    <div class="rail-group-sub" id="rail-sub-dashboards">
      {% for topic in topics %}
      <a class="rail-sub-link" href="{{ topic.topic|lower|replace(' ','_')|replace('/','_') }}.html" target="_blank" rel="noopener">
        <span class="rail-sub-dot" style="background:{{ topic.color }};"></span>{{ topic.topic }}
      </a>
      {% endfor %}
    </div>

    <!-- ── 2. News & Articles ── -->
    <div class="rail-group-header" id="rail-grp-news" data-group="news" onclick="toggleRailGroup('news', event)">
      <i data-lucide="newspaper" style="width:16px;height:16px;color:#60A5FA;flex-shrink:0;"></i>
      <span class="rail-group-label">News &amp; Articles</span>
      <span class="rail-group-chevron">&#9654;</span>
    </div>
    <div class="rail-group-sub" id="rail-sub-news">
      {% for topic in topics %}
      <a class="rail-sub-link" onclick="expandTopic('{{ topic.topic|lower }}')">
        <span class="rail-sub-dot" style="background:{{ topic.color }};"></span>{{ topic.topic }}
      </a>
      {% endfor %}
    </div>

    <!-- ── 3. Deadlines ── -->
    <div class="rail-group-header" id="rail-grp-deadlines" data-group="deadlines" data-sections="section-deadlines,section-calendar" onclick="toggleRailGroup('deadlines', event)">
      <i data-lucide="triangle-alert" style="width:16px;height:16px;color:#D97706;flex-shrink:0;"></i>
      <span class="rail-group-label">Deadlines</span>
      <span class="rail-group-chevron">&#9654;</span>
    </div>
    <div class="rail-group-sub" id="rail-sub-deadlines">
      <a class="rail-sub-link" onclick="scrollToSection('section-deadlines')">All Deadlines</a>
      {% for topic in topics %}
      <a class="rail-sub-link" onclick="scrollToSection('section-deadlines');filterDeadlinesByTopic('{{ topic.topic|lower }}')">
        <span class="rail-sub-dot" style="background:{{ topic.color }};"></span>{{ topic.topic }}
      </a>
      {% endfor %}
      <a class="rail-sub-link" onclick="scrollToSection('section-calendar')">Reg. Calendar</a>
    </div>

    <!-- ── 4. Maps ── -->
    <div class="rail-group-header" id="rail-grp-maps" data-group="maps" onclick="toggleRailGroup('maps', event)">
      <i data-lucide="globe" style="width:16px;height:16px;color:#7C3AED;flex-shrink:0;"></i>
      <span class="rail-group-label">Maps</span>
      <span class="rail-group-chevron">&#9654;</span>
    </div>
    <div class="rail-group-sub" id="rail-sub-maps">
      {% if maps.pfas_map_url %}<a class="rail-sub-link" href="{{ maps.pfas_map_url }}" target="_blank" rel="noopener">PFAS State Map</a>{% endif %}
      {% if maps.pfas_intel_url %}<a class="rail-sub-link" href="{{ maps.pfas_intel_url }}" target="_blank" rel="noopener">PFAS Intel Map</a>{% endif %}
      {% if maps.epr_map_url %}<a class="rail-sub-link" href="{{ maps.epr_map_url }}" target="_blank" rel="noopener">EPR Map</a>{% endif %}
      {% if maps.reach_map_url %}<a class="rail-sub-link" href="{{ maps.reach_map_url }}" target="_blank" rel="noopener">REACH Map</a>{% endif %}
    </div>

    <!-- ── 5. Timelines ── -->
    <div class="rail-group-header" id="rail-grp-timelines" data-group="timelines" onclick="toggleRailGroup('timelines', event)">
      <i data-lucide="gantt-chart" style="width:16px;height:16px;color:#0369A1;flex-shrink:0;"></i>
      <span class="rail-group-label">Timelines</span>
      <span class="rail-group-chevron">&#9654;</span>
    </div>
    <div class="rail-group-sub" id="rail-sub-timelines">
      {% if timelines.all %}<a class="rail-sub-link" href="{{ timelines.all }}" target="_blank" rel="noopener">All Topics</a>{% endif %}
      {% if timelines.pfas %}<a class="rail-sub-link" href="{{ timelines.pfas }}" target="_blank" rel="noopener">PFAS</a>{% endif %}
      {% if timelines.epr %}<a class="rail-sub-link" href="{{ timelines.epr }}" target="_blank" rel="noopener">EPR</a>{% endif %}
      {% if timelines.reach %}<a class="rail-sub-link" href="{{ timelines.reach }}" target="_blank" rel="noopener">REACH</a>{% endif %}
      {% if timelines.tsca %}<a class="rail-sub-link" href="{{ timelines.tsca }}" target="_blank" rel="noopener">TSCA</a>{% endif %}
    </div>

    <!-- ── 6. Legislative ── -->
    <div class="rail-group-header" id="rail-grp-legislative" data-group="legislative" data-sections="section-leg-activity,section-cross-state,section-changes" onclick="toggleRailGroup('legislative', event)">
      <i data-lucide="landmark" style="width:16px;height:16px;color:#BE185D;flex-shrink:0;"></i>
      <span class="rail-group-label">Legislative</span>
      <span class="rail-group-chevron">&#9654;</span>
    </div>
    <div class="rail-group-sub" id="rail-sub-legislative">
      {% if bill_activity %}<a class="rail-sub-link" onclick="scrollToSection('section-leg-activity')">Bill Activity</a>{% endif %}
      {% if cross_state_reports %}<a class="rail-sub-link" onclick="scrollToSection('section-cross-state')">Cross-State Intel</a>{% endif %}
      {% if daily_changes %}<a class="rail-sub-link" onclick="scrollToSection('section-changes')">Changes Today</a>{% endif %}
    </div>

    <!-- ── 7. Downloads & Archive ── -->
    <div class="rail-group-header" id="rail-grp-downloads" data-group="downloads" data-sections="section-archive" onclick="toggleRailGroup('downloads', event)">
      <i data-lucide="archive" style="width:16px;height:16px;color:#4B5563;flex-shrink:0;"></i>
      <span class="rail-group-label">Downloads &amp; Archive</span>
      <span class="rail-group-chevron">&#9654;</span>
    </div>
    <div class="rail-group-sub" id="rail-sub-downloads">
      {% if downloads.pfas_xlsx %}<a class="rail-sub-link" href="{{ downloads.pfas_xlsx }}" target="_blank" rel="noopener">PFAS Tracker (.xlsx)</a>{% endif %}
      {% if downloads.epr_xlsx %}<a class="rail-sub-link" href="{{ downloads.epr_xlsx }}" target="_blank" rel="noopener">EPR Tracker (.xlsx)</a>{% endif %}
      {% if downloads.reach_xlsx %}<a class="rail-sub-link" href="{{ downloads.reach_xlsx }}" target="_blank" rel="noopener">REACH Tracker (.xlsx)</a>{% endif %}
      {% if calendar_url %}<a class="rail-sub-link" href="{{ calendar_url }}">Calendar (.ics)</a>{% endif %}
      <a class="rail-sub-link" onclick="scrollToSection('section-archive')">Archive</a>
    </div>

    <div class="rail-divider"></div>

    <!-- ── Special pinned items ── -->
    <a class="rail-link-amber" href="glossary.html" target="_blank" rel="noopener">
      <i data-lucide="book-open" style="width:16px;height:16px;flex-shrink:0;"></i>
      <span class="rail-label">Glossary</span>
    </a>
    <a class="rail-link-purple" href="director_review.html" target="_blank" rel="noopener">
      <i data-lucide="eye" style="width:16px;height:16px;flex-shrink:0;"></i>
      <span class="rail-label">Director Review</span>
    </a>

  </div>
```

- [ ] **Step 2: Commit**
```bash
git add dashboard/templates/dashboard.html
git commit -m "feat(sidebar): replace flat nav with accordion groups"
```

---

## Task 4: Add accordion JavaScript

**Files:**
- Modify: `dashboard/templates/dashboard.html` (sidebar JS block, ~line 3374)

Replace the existing sidebar JS section (lines 3374–3430 — `toggleSidebar` through the `toggleSidebarPersist` restore IIFE) with the following. Keep the `toggleExec` block that follows it unchanged.

- [ ] **Step 1: Replace the sidebar JS block**

Find:
```js
  window.toggleSidebar = function() {
    document.getElementById('sidebar').classList.toggle('open');
  };
```

...through to (inclusive):
```js
  // Restore sidebar state on load
  (function() {
    if (localStorage.getItem('sidebarCollapsed') === '1') {
      document.body.classList.add('sidebar-collapsed');
    }
  })();
```

Replace the entire range with:

```js
  /* ── Mobile sidebar toggle ── */
  window.toggleSidebar = function() {
    document.getElementById('sidebar').classList.toggle('open');
  };

  /* ── Right-panel hide/show ── */
  window.toggleSidebarPanel = function() {
    var gridMain = document.querySelector('.grid-main');
    if (!gridMain) return;
    var hidden = gridMain.classList.toggle('sidebar-hidden');
    var btn = document.getElementById('sidebar-collapse-btn');
    if (btn) btn.style.cssText = hidden ? 'display:none' : '';
    var showBtn = document.getElementById('sidebar-show-btn');
    if (showBtn) showBtn.style.display = hidden ? 'block' : 'none';
  };

  /* ── Smooth scroll to section ── */
  window.scrollToSection = function(id) {
    var anchor = document.getElementById('anchor-' + id) || document.getElementById(id);
    if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  /* ── Accordion: default open groups ── */
  var ACCORDION_DEFAULTS = { dashboards: true, news: true };

  function loadAccordionState() {
    try {
      var saved = JSON.parse(localStorage.getItem('sidebarAccordion') || '{}');
      return Object.assign({}, ACCORDION_DEFAULTS, saved);
    } catch(e) { return Object.assign({}, ACCORDION_DEFAULTS); }
  }

  function saveAccordionState(state) {
    try { localStorage.setItem('sidebarAccordion', JSON.stringify(state)); } catch(e) {}
  }

  function applyAccordionState(state) {
    Object.keys(state).forEach(function(groupId) {
      var hdr = document.getElementById('rail-grp-' + groupId);
      var sub = document.getElementById('rail-sub-' + groupId);
      if (!hdr || !sub) return;
      if (state[groupId]) {
        hdr.classList.add('open');
        sub.classList.add('open');
      } else {
        hdr.classList.remove('open');
        sub.classList.remove('open');
      }
    });
  }

  window.toggleRailGroup = function(groupId, e) {
    /* If rail is collapsed, expand it first then open the group */
    if (document.body.classList.contains('sidebar-collapsed')) {
      document.body.classList.remove('sidebar-collapsed');
      localStorage.setItem('sidebarCollapsed', '0');
    }
    var hdr = document.getElementById('rail-grp-' + groupId);
    var sub = document.getElementById('rail-sub-' + groupId);
    if (!hdr || !sub) return;
    var nowOpen = hdr.classList.toggle('open');
    sub.classList.toggle('open', nowOpen);
    var state = loadAccordionState();
    state[groupId] = nowOpen;
    saveAccordionState(state);
  };

  /* Restore accordion state on load */
  (function() {
    applyAccordionState(loadAccordionState());
  })();

  /* ── Active group tracking on scroll ── */
  /* Maps group IDs to the section IDs they track (external-only groups omitted) */
  var RAIL_GROUP_SECTIONS = {
    'news':        {{ topics|map(attribute='topic')|map('lower')|list|tojson }}.map(function(t){ return 'section-' + t; }),
    'deadlines':   ['section-deadlines'],
    'legislative': ['section-leg-activity', 'section-cross-state', 'section-changes'],
    'downloads':   ['section-archive']
  };
  /* Flat links that track by data-target attribute (Overview + Reg. Calendar) */

  function updateActiveRailLink() {
    var scrollY = window.scrollY + 80;

    /* Collect all trackable section positions */
    var candidates = [];

    /* Flat links */
    document.querySelectorAll('.rail-link[data-target]').forEach(function(link) {
      var el = document.getElementById(link.dataset.target);
      if (el) candidates.push({ type: 'link', el: el, node: link, top: el.offsetTop });
    });

    /* Group headers */
    Object.keys(RAIL_GROUP_SECTIONS).forEach(function(groupId) {
      RAIL_GROUP_SECTIONS[groupId].forEach(function(sectionId) {
        var el = document.getElementById(sectionId);
        if (el) candidates.push({ type: 'group', el: el, node: document.getElementById('rail-grp-' + groupId), top: el.offsetTop });
      });
    });

    /* Sort by top position */
    candidates.sort(function(a, b) { return a.top - b.top; });

    /* Find active candidate */
    var active = candidates[0];
    for (var i = candidates.length - 1; i >= 0; i--) {
      if (candidates[i].top <= scrollY) { active = candidates[i]; break; }
    }

    /* Clear all active states */
    document.querySelectorAll('.rail-link.active').forEach(function(l) { l.classList.remove('active'); });
    document.querySelectorAll('.rail-group-header.active').forEach(function(h) { h.classList.remove('active'); });

    /* Apply active to winning candidate */
    if (active && active.node) active.node.classList.add('active');
  }

  var scrollTick = false;
  window.addEventListener('scroll', function() {
    if (!scrollTick) {
      requestAnimationFrame(function() { updateActiveRailLink(); scrollTick = false; });
      scrollTick = true;
    }
  });
  updateActiveRailLink();

  /* ── Rail width collapse (persisted) ── */
  window.toggleSidebarPersist = function() {
    document.body.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebarCollapsed', document.body.classList.contains('sidebar-collapsed') ? '1' : '0');
  };
  (function() {
    if (localStorage.getItem('sidebarCollapsed') === '1') {
      document.body.classList.add('sidebar-collapsed');
    }
  })();
```

- [ ] **Step 2: Commit**
```bash
git add dashboard/templates/dashboard.html
git commit -m "feat(sidebar): add accordion JS with localStorage persistence"
```

---

## Task 5: Add `filterDeadlinesByTopic` stub

The Deadlines sub-items call `filterDeadlinesByTopic(topic)`. This function needs to exist (it filters the deadline list to a topic). Check if it already exists first.

**Files:**
- Modify: `dashboard/templates/dashboard.html`

- [ ] **Step 1: Check if the function already exists**

```bash
grep -n "filterDeadlinesByTopic\|deadlineFilter\|dl-filter" dashboard/templates/dashboard.html | head -20
```

- [ ] **Step 2a: If the function exists** — confirm the name matches `filterDeadlinesByTopic(topicName)` and that calling it with a lowercase topic string (e.g. `'pfas'`) correctly filters the deadline list. If the existing function has a different name, update the `onclick` attributes in Task 3's HTML to use the correct name.

- [ ] **Step 2b: If the function does NOT exist** — add this stub at the end of the main `<script>` block (just before the closing `})();` of the IIFE, around line 4674):

```js
  /* Filter deadline cards to a specific topic. Called from sidebar. */
  window.filterDeadlinesByTopic = function(topicName) {
    var cards = document.querySelectorAll('.deadline-card, [data-deadline-topic]');
    cards.forEach(function(card) {
      var t = (card.dataset.deadlineTopic || card.dataset.topic || '').toLowerCase();
      card.style.display = (!topicName || t === topicName) ? '' : 'none';
    });
    /* Highlight the matching filter button if one exists */
    document.querySelectorAll('[data-dl-filter]').forEach(function(btn) {
      btn.classList.toggle('active', btn.dataset.dlFilter === topicName);
    });
  };
```

- [ ] **Step 3: Commit**
```bash
git add dashboard/templates/dashboard.html
git commit -m "feat(sidebar): add filterDeadlinesByTopic for deadline sub-links"
```

---

## Task 6: Preview and verify

- [ ] **Step 1: Generate preview**
```bash
source .venv/bin/activate && python run.py --preview
```
Expected: browser opens with dashboard.

- [ ] **Step 2: Visual checks**

Open browser DevTools console and run each check:

```js
// 1. Icons rendered
document.querySelectorAll('[data-lucide]').length
// Expected: > 0 (all icon placeholders replaced by SVGs)

// 2. Accordion groups present
document.querySelectorAll('.rail-group-header').length
// Expected: 7

// 3. Dashboards and News open by default
document.getElementById('rail-grp-dashboards').classList.contains('open')
// Expected: true
document.getElementById('rail-grp-news').classList.contains('open')
// Expected: true

// 4. Other groups collapsed
document.getElementById('rail-grp-maps').classList.contains('open')
// Expected: false

// 5. News click expands topic card
expandTopic('pfas')
// Expected: PFAS card expands and scrolls into view
```

- [ ] **Step 3: Accordion toggle check**

Click the "Maps" group header in the sidebar. Confirm:
- Sub-items slide into view
- Chevron rotates 90°
- Reload page — Maps stays open (localStorage persisted)

- [ ] **Step 4: Collapsed rail check**

Click the `«` toggle button at the bottom of the sidebar. Confirm:
- Rail collapses to 56px
- Only icons visible
- Click the "layers" (Dashboards) icon — rail expands and Dashboards group opens

- [ ] **Step 5: Commit**
```bash
git add dashboard/templates/dashboard.html
git commit -m "feat(sidebar): verified accordion behavior in preview"
```

---

## Task 7: Publish

- [ ] **Step 1: Push to GitHub Pages (no email)**
```bash
source .venv/bin/activate && python run.py --no-email 2>&1 | grep -E "INFO.*dashboard|INFO.*pushed|Done\."
```
Expected output includes:
```
INFO     github_dashboard: Dashboard pushed: https://ryan-jenkinson.github.io/compliance-maps/dashboard.html
INFO     run: Done. Subscriber emails skipped (--no-email).
```

- [ ] **Step 2: Verify live**

Open `https://ryan-jenkinson.github.io/compliance-maps/dashboard.html` and confirm accordion sidebar is present.

- [ ] **Step 3: Final commit tag**
```bash
git add dashboard/templates/dashboard.html
git commit -m "feat(sidebar): accordion nav live on GitHub Pages"
```
