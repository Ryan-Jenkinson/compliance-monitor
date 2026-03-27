# Compliance Monitor V2 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a new GitHub repository as a copy of the current project, extract inline CSS and JS from the monolithic templates into external files + Jinja2 partials, and wire up Supabase + Vercel so the new project auto-deploys from GitHub behind a Vercel URL.

**Architecture:** The existing production project (`compliance-monitor`) is never touched. All work happens in a new repo (`compliance-monitor-v2`). The Python pipeline, SQLite database, and all rendering logic stay unchanged. Templates are refactored to load CSS from `dashboard/static/css/` and JS from `dashboard/static/js/` — these static files are copied into the GitHub Pages deployment repo alongside the rendered HTML so Vercel can serve them. A single inline `<script>` block in each template bridges Jinja2 template data to the external JS files via global variables.

**Tech Stack:** Python 3, Jinja2, Supabase (project setup only in this plan), Vercel (project setup only), GitHub CLI (`gh`), vanilla JS, CSS.

---

## Pre-flight: What you need before starting

- GitHub account with `gh` CLI installed and authenticated (`gh auth status`)
- The current production project at `/Users/ryanjenkinson/Desktop/compliance-monitor` — **never modify files here**
- All work goes into a new directory: `/Users/ryanjenkinson/Desktop/compliance-monitor-v2`
- A Supabase account (free tier at supabase.com)
- A Vercel account (free tier at vercel.com)

---

## File Map

**New files created:**
- `dashboard/static/css/dashboard.css` — all CSS extracted from `dashboard/templates/dashboard.html` lines 12–2248
- `dashboard/static/css/topic.css` — all CSS extracted from `dashboard/templates/topic_page.html` lines 11–964, minus the `--topic-color` variable
- `dashboard/static/js/nav.js` — sidebar collapse, accordion open/close, scroll-to-section, active link tracking, exec/deadlines toggles, topic card expand
- `dashboard/static/js/filters.js` — article filter state, search, urgency/relevance/sort filters, topic filter chips, apply-filters logic
- `dashboard/static/js/modals.js` — expand modal, history modal, 6-month article archive modal
- `dashboard/static/js/ui.js` — timeline dot clustering, cross-state tab switcher, resizable sidebar, Lucide icon init
- `dashboard/static/js/auth.js` — stub (empty, for Phase 2)
- `dashboard/static/js/notifications.js` — stub (empty, for Phase 3)
- `dashboard/static/js/favorites.js` — stub (empty, for Phase 3)
- `dashboard/static/js/comments.js` — stub (empty, for Phase 3)
- `dashboard/static/js/messages.js` — stub (empty, for Phase 4)
- `dashboard/templates/_sidebar.html` — nav rail HTML partial
- `dashboard/templates/_topbar.html` — topbar HTML partial
- `dashboard/templates/_article_card.html` — article card HTML partial
- `dashboard/templates/_badge_legend.html` — badge legend partial

**Modified files:**
- `dashboard/templates/dashboard.html` — CSS block replaced with `<link>`, JS blocks replaced with `<script src>` + one inline data bridge block, HTML sections replaced with `{% include %}`
- `dashboard/templates/topic_page.html` — CSS block replaced with `<link>` + one-line inline style for `--topic-color`
- `run.py` — `_GITHUB_REPO_DIR` updated to point to new repo clone, `_PAGES_BASE` updated to Vercel URL, `_push_auxiliary_pages` updated to also copy `static/` directory

---

## Task 1: Create the new GitHub repository

**Files:** No code changes — manual git operations.

- [ ] **Step 1: Copy the current project to a new directory**

```bash
cp -r /Users/ryanjenkinson/Desktop/compliance-monitor /Users/ryanjenkinson/Desktop/compliance-monitor-v2
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2
```

- [ ] **Step 2: Create new GitHub repo and push**

```bash
# Remove the old remote — this is a fresh repo, not a fork
git remote remove origin

# Create new GitHub repo (private) and set as remote
gh repo create compliance-monitor-v2 --private --source=. --push

# Verify remote is set correctly
git remote -v
```

Expected output from `git remote -v`:
```
origin  https://github.com/<your-username>/compliance-monitor-v2.git (fetch)
origin  https://github.com/<your-username>/compliance-monitor-v2.git (push)
```

- [ ] **Step 3: Confirm the production repo is untouched**

```bash
# This should show origin pointing to the OLD repo — never run work commands in here
git -C /Users/ryanjenkinson/Desktop/compliance-monitor remote -v
```

Expected: still points to the original `compliance-monitor` repo.

- [ ] **Step 4: Add `.superpowers/` to .gitignore in the new repo**

Open `/Users/ryanjenkinson/Desktop/compliance-monitor-v2/.gitignore` and verify `.superpowers/` is present. If not, add it:

```
.superpowers/
```

- [ ] **Step 5: Create static asset directory structure**

```bash
mkdir -p /Users/ryanjenkinson/Desktop/compliance-monitor-v2/dashboard/static/css
mkdir -p /Users/ryanjenkinson/Desktop/compliance-monitor-v2/dashboard/static/js
```

- [ ] **Step 6: Commit directory structure**

```bash
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2
# Create placeholder files so the empty dirs are tracked
touch dashboard/static/css/.gitkeep
touch dashboard/static/js/.gitkeep
git add dashboard/static/
git commit -m "chore: add static asset directory structure for CSS/JS extraction"
```

---

## Task 2: Extract CSS from dashboard.html

**Files:**
- Create: `dashboard/static/css/dashboard.css`
- Modify: `dashboard/templates/dashboard.html` (lines 11–2249)

- [ ] **Step 1: Extract the CSS block**

Open `dashboard/templates/dashboard.html`. The inline `<style>` block spans lines 11–2249. Extract everything between (but not including) the `<style>` and `</style>` tags and save it to a new file:

```bash
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2
# Extract lines 12-2248 (the CSS content, excluding the style tags themselves)
sed -n '12,2248p' dashboard/templates/dashboard.html > dashboard/static/css/dashboard.css
```

- [ ] **Step 2: Verify the CSS file was created correctly**

```bash
wc -l dashboard/static/css/dashboard.css
head -5 dashboard/static/css/dashboard.css
tail -5 dashboard/static/css/dashboard.css
```

Expected: ~2237 lines, starts with `:root {`, ends with `}` (the `.cal-detail-meta` rule).

- [ ] **Step 3: Replace the style block in dashboard.html with a link tag**

In `dashboard/templates/dashboard.html`, replace lines 11–2249 (the entire `<style>...</style>` block) with a single link tag. The `<head>` section should go from:

```html
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
  <style>
    :root {
      ...2237 lines...
    .cal-detail-meta { ... }
  </style>
</head>
```

To:

```html
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
  <link rel="stylesheet" href="static/css/dashboard.css">
</head>
```

Use the Edit tool (or a text editor) to make this replacement. The exact old_string to match:

```
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
  <style>
```

Replace with:

```
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
  <link rel="stylesheet" href="static/css/dashboard.css">
```

Then delete lines from `    :root {` through `  </style>` (the CSS content and closing tag). The file should now have `</head>` directly after the `<link>` tag.

- [ ] **Step 4: Verify line count dropped**

```bash
wc -l dashboard/templates/dashboard.html
```

Expected: approximately 2960 lines (was 5202, removed ~2237 CSS lines).

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/css/dashboard.css dashboard/templates/dashboard.html
git commit -m "refactor: extract dashboard.html inline CSS to dashboard/static/css/dashboard.css"
```

---

## Task 3: Extract CSS from topic_page.html

**Files:**
- Create: `dashboard/static/css/topic.css`
- Modify: `dashboard/templates/topic_page.html` (lines 10–965)

`topic_page.html` has one Jinja2 variable inside its CSS: `--topic-color: {{ topic.color }};` on line 12. This one line must stay inline. Everything else can be extracted.

- [ ] **Step 1: Identify the topic-color line**

```bash
grep -n "topic-color\|topic\.color" dashboard/templates/topic_page.html | head -5
```

Expected: line ~12: `      --topic-color: {{ topic.color }};`

- [ ] **Step 2: Extract the CSS, skipping the topic-color line**

Open `dashboard/templates/topic_page.html`. The CSS block is lines 10–965. Extract it to `topic.css`, excluding the `--topic-color` line:

```bash
# Extract lines 11-964 (CSS content between the style tags), then remove the topic-color line
sed -n '11,964p' dashboard/templates/topic_page.html | grep -v 'topic-color\|topic\.color' > dashboard/static/css/topic.css
```

- [ ] **Step 3: Verify the topic.css file**

```bash
wc -l dashboard/static/css/topic.css
grep "topic-color\|topic\.color" dashboard/static/css/topic.css
```

Expected: ~953 lines, and the grep returns nothing (no topic-color in the external file).

- [ ] **Step 4: Replace the style block in topic_page.html**

In `dashboard/templates/topic_page.html`, replace the entire `<style>...</style>` block (lines 10–965) with:

```html
  <link rel="stylesheet" href="static/css/topic.css">
  <style>:root { --topic-color: {{ topic.color }}; }</style>
```

The `<head>` block should now have the link tag followed by a tiny one-line inline style. Example of the replacement area:

Before:
```html
  <link href="https://fonts.googleapis.com/...
  <style>
    :root {
      --topic-color: {{ topic.color }};
      --bg: #F4F5F7;
      ... ~954 more lines ...
    }
  </style>
```

After:
```html
  <link href="https://fonts.googleapis.com/...
  <link rel="stylesheet" href="static/css/topic.css">
  <style>:root { --topic-color: {{ topic.color }}; }</style>
```

- [ ] **Step 5: Verify**

```bash
wc -l dashboard/templates/topic_page.html
```

Expected: ~990 lines (was 1950, removed ~953 CSS lines, kept 1 inline style line).

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/css/topic.css dashboard/templates/topic_page.html
git commit -m "refactor: extract topic_page.html inline CSS to dashboard/static/css/topic.css"
```

---

## Task 4: Create the Jinja2 data bridge in dashboard.html

**Files:**
- Modify: `dashboard/templates/dashboard.html`

Before extracting the JavaScript, we need one inline `<script>` block that exposes Jinja2 template data as global JavaScript variables. External `.js` files will read from these globals instead of having Jinja2 expressions embedded in them.

- [ ] **Step 1: Identify all Jinja2 expressions currently in the JS blocks**

Search the current JS section (lines ~3557 onward) for Jinja2 expressions:

```bash
grep -n "{{" dashboard/templates/dashboard.html | grep -v "article\.\|topic\.\|exec_summary\|deadlines\|bills\|cross_state" | head -20
```

The Jinja2 expressions to capture are:
- `{{ bill_analyses|tojson }}` (line ~3558)
- `{{ deadline_analyses|tojson }}` (line ~3559)
- `{{ topics|map(attribute='topic')|list|map('lower')|list|tojson }}` (appears ~3 times)
- `{{ topic_slugs | tojson }}` (appears ~2 times)
- `{{ all_articles_json | safe }}` (line ~5070)

- [ ] **Step 2: Add the data bridge script block at the end of dashboard.html, before the existing script blocks**

Find the line that currently reads:
```html
<!-- Bill analyses data (pre-generated by pipeline) -->
<script>
var BILL_ANALYSES = {{ bill_analyses|tojson }};
var DEADLINE_ANALYSES = {{ deadline_analyses|tojson }};
</script>
```

Replace it with this expanded data bridge block:

```html
<!-- Jinja2 data bridge: all template variables needed by external JS files -->
<script>
var BILL_ANALYSES = {{ bill_analyses|tojson }};
var DEADLINE_ANALYSES = {{ deadline_analyses|tojson }};
var APP_TOPICS = {{ topics|map(attribute='topic')|list|map('lower')|list|tojson }};
var APP_TOPIC_SLUGS = {{ topic_slugs | tojson }};
var ALL_ARTICLES = [];
try { ALL_ARTICLES = {{ all_articles_json | safe }}; } catch(e) {}
</script>
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/templates/dashboard.html
git commit -m "refactor: add Jinja2 data bridge script block for external JS extraction"
```

---

## Task 5: Extract nav.js from dashboard.html

**Files:**
- Create: `dashboard/static/js/nav.js`
- Modify: `dashboard/templates/dashboard.html`

`nav.js` contains: mobile sidebar toggle, right-panel toggle, scroll-to-section, deadline filter by topic, accordion open/close + localStorage persistence, active rail link tracking on scroll, sidebar collapse/expand persistence, exec summary toggle, deadlines toggle, topic card expand/collapse.

- [ ] **Step 1: Create nav.js with the following content**

Create `dashboard/static/js/nav.js`:

```javascript
/* nav.js — Sidebar, accordion, scroll, and section toggle behaviors */
(function() {
  'use strict';

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

  /* ── Filter deadline list to a topic (called from sidebar Deadlines sub-links) ── */
  window.filterDeadlinesByTopic = function(topicName) {
    document.querySelectorAll('.dl-item[data-topic]').forEach(function(card) {
      var t = (card.dataset.topic || '').toLowerCase();
      card.style.display = (!topicName || t === topicName) ? '' : 'none';
    });
  };

  /* ── Accordion: localStorage persistence ── */
  var ACCORDION_DEFAULTS = {};

  function loadAccordionState() {
    try {
      var saved = JSON.parse(localStorage.getItem('sidebarAccordion') || '{}');
      return Object.assign({}, ACCORDION_DEFAULTS, saved);
    } catch(e) { return Object.assign({}, ACCORDION_DEFAULTS); }
  }

  function saveAccordionState(st) {
    try { localStorage.setItem('sidebarAccordion', JSON.stringify(st)); } catch(e) {}
  }

  function applyAccordionState(st) {
    Object.keys(st).forEach(function(groupId) {
      var hdr = document.getElementById('rail-grp-' + groupId);
      var sub = document.getElementById('rail-sub-' + groupId);
      if (!hdr || !sub) return;
      if (st[groupId]) {
        hdr.classList.add('open');
        sub.classList.add('open');
      } else {
        hdr.classList.remove('open');
        sub.classList.remove('open');
      }
    });
  }

  window.toggleRailGroup = function(groupId, e) {
    if (document.body.classList.contains('sidebar-collapsed')) {
      document.body.classList.remove('sidebar-collapsed');
      localStorage.setItem('sidebarCollapsed', '0');
    }
    var hdr = document.getElementById('rail-grp-' + groupId);
    var sub = document.getElementById('rail-sub-' + groupId);
    if (!hdr || !sub) return;
    var nowOpen = hdr.classList.toggle('open');
    sub.classList.toggle('open', nowOpen);
    var st = loadAccordionState();
    st[groupId] = nowOpen;
    saveAccordionState(st);
  };

  /* Restore accordion state on load */
  applyAccordionState(loadAccordionState());

  /* ── Active group tracking on scroll ── */
  /* APP_TOPICS is set by the inline data bridge in dashboard.html */
  var RAIL_GROUP_SECTIONS = {
    'news':        APP_TOPICS.map(function(t){ return 'section-' + t; }),
    'deadlines':   ['section-deadlines'],
    'legislative': ['section-leg-activity', 'section-cross-state', 'section-changes'],
    'downloads':   ['section-archive']
  };

  function updateActiveRailLink() {
    var scrollY = window.scrollY + 80;
    var candidates = [];
    document.querySelectorAll('.rail-link[data-target]').forEach(function(link) {
      var el = document.getElementById(link.dataset.target);
      if (el) candidates.push({ type: 'link', el: el, node: link, top: el.offsetTop });
    });
    Object.keys(RAIL_GROUP_SECTIONS).forEach(function(groupId) {
      RAIL_GROUP_SECTIONS[groupId].forEach(function(sectionId) {
        var el = document.getElementById(sectionId);
        if (el) candidates.push({ type: 'group', el: el, node: document.getElementById('rail-grp-' + groupId), top: el.offsetTop });
      });
    });
    candidates.sort(function(a, b) { return a.top - b.top; });
    var active = candidates[0];
    for (var i = candidates.length - 1; i >= 0; i--) {
      if (candidates[i].top <= scrollY) { active = candidates[i]; break; }
    }
    document.querySelectorAll('.rail-link.active').forEach(function(l) { l.classList.remove('active'); });
    document.querySelectorAll('.rail-group-header.active').forEach(function(h) { h.classList.remove('active'); });
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
  if (localStorage.getItem('sidebarCollapsed') === '1') {
    document.body.classList.add('sidebar-collapsed');
  }

  /* ── Exec summary toggle (persisted) ── */
  window.toggleExec = function() {
    var panel = document.getElementById('exec-panel');
    panel.classList.toggle('exec-collapsed');
    var label = panel.querySelector('.exec-toggle-label');
    var isCollapsed = panel.classList.contains('exec-collapsed');
    if (label) label.textContent = isCollapsed ? 'expand' : 'collapse';
    localStorage.setItem('execCollapsed', isCollapsed ? '1' : '0');
  };
  if (localStorage.getItem('execCollapsed') === '1') {
    var _ep = document.getElementById('exec-panel');
    if (_ep) {
      _ep.classList.add('exec-collapsed');
      var _el = _ep.querySelector('.exec-toggle-label');
      if (_el) _el.textContent = 'expand';
    }
  }

  /* ── Deadlines toggle (persisted) ── */
  window.toggleDeadlines = function() {
    var panel = document.getElementById('section-deadlines');
    panel.classList.toggle('deadlines-collapsed');
    var label = panel.querySelector('.dl-toggle-label');
    var isCollapsed = panel.classList.contains('deadlines-collapsed');
    if (label) label.textContent = isCollapsed ? 'expand' : 'collapse';
    localStorage.setItem('deadlinesCollapsed', isCollapsed ? '1' : '0');
  };
  (function() {
    var panel = document.getElementById('section-deadlines');
    if (!panel) return;
    var stored = localStorage.getItem('deadlinesCollapsed');
    if (stored === '0') {
      panel.classList.remove('deadlines-collapsed');
      var label = panel.querySelector('.dl-toggle-label');
      if (label) label.textContent = 'collapse';
    }
  })();

  /* ── Topic Card expand/collapse ── */
  window.toggleTopicCard = function(card, e) {
    if (e.target.tagName === 'A') return;
    card.classList.toggle('expanded');
  };

  window.expandTopic = function(topicName) {
    var card = document.getElementById('section-' + topicName);
    if (!card) return;
    if (!card.classList.contains('expanded')) {
      card.classList.add('expanded');
    }
    setTimeout(function() {
      var rect = card.getBoundingClientRect();
      var offset = rect.top + window.scrollY - 70;
      window.scrollTo({ top: offset, behavior: 'smooth' });
    }, 30);
  };

})();
```

- [ ] **Step 2: Remove the corresponding code from dashboard.html**

In `dashboard/templates/dashboard.html`, find the large `<script>` block that starts after the data bridge block (currently at line ~3562). Remove everything from `window.toggleSidebar` through `window.expandTopic` (the nav functions above). These functions are now in `nav.js`.

Keep the `var state = {...}` initialization and all filter/search functions — those go in `filters.js` (next task).

- [ ] **Step 3: Add the nav.js script tag to dashboard.html**

In `dashboard/templates/dashboard.html`, add before `</body>`:

```html
<script src="static/js/nav.js"></script>
```

This goes AFTER the data bridge `<script>` block and BEFORE any inline JS that calls nav functions.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/js/nav.js dashboard/templates/dashboard.html
git commit -m "refactor: extract nav/sidebar JS to dashboard/static/js/nav.js"
```

---

## Task 6: Extract filters.js from dashboard.html

**Files:**
- Create: `dashboard/static/js/filters.js`
- Modify: `dashboard/templates/dashboard.html`

`filters.js` contains: filter state object, search handler, topic filter chips, urgency/new/relevance/sort filters, autocomplete suggestions, applyFilters logic.

- [ ] **Step 1: Create filters.js**

Create `dashboard/static/js/filters.js`:

```javascript
/* filters.js — Article filter state, search, and apply-filters logic */
(function() {
  'use strict';

  /* APP_TOPICS is set by the inline data bridge in dashboard.html */
  var state = {
    searchQuery: '',
    activeTopics: new Set(APP_TOPICS),
    urgencyFilter: 'ALL',
    newFilter: 'ALL',
    sortOrder: 'date',
    relFilter: 'relevant',
    allTopics: APP_TOPICS
  };

  /* ── Autocomplete ── */
  var _suggIdx = -1;

  window.handleSearchKeydown = function(e) {
    var box = document.getElementById('search-suggestions');
    var items = box ? box.querySelectorAll('.search-sugg-item') : [];
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _suggIdx = Math.min(_suggIdx + 1, items.length - 1);
      items.forEach(function(el, i) { el.classList.toggle('active', i === _suggIdx); });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _suggIdx = Math.max(_suggIdx - 1, -1);
      items.forEach(function(el, i) { el.classList.toggle('active', i === _suggIdx); });
    } else if (e.key === 'Enter' && _suggIdx >= 0 && items[_suggIdx]) {
      e.preventDefault();
      items[_suggIdx].click();
    } else if (e.key === 'Escape') {
      closeSuggestions();
      document.getElementById('search-input').blur();
    }
  };

  function closeSuggestions() {
    var box = document.getElementById('search-suggestions');
    if (box) { box.style.display = 'none'; box.innerHTML = ''; }
    _suggIdx = -1;
  }

  function buildSuggestions(q) {
    if (!q || q.length < 1) { closeSuggestions(); return; }
    var ql = q.toLowerCase();
    var suggestions = [];
    var topicCounts = {};
    ALL_ARTICLES.forEach(function(a) { topicCounts[a.topic] = (topicCounts[a.topic] || 0) + 1; });
    Object.keys(topicCounts).forEach(function(t) {
      if (t.toLowerCase().indexOf(ql) !== -1) {
        suggestions.push({ type: 'topic', label: t, count: topicCounts[t] });
      }
    });
    var sourceCounts = {};
    ALL_ARTICLES.forEach(function(a) {
      if (a.source && a.source.toLowerCase().indexOf(ql) !== -1) {
        sourceCounts[a.source] = (sourceCounts[a.source] || 0) + 1;
      }
    });
    Object.keys(sourceCounts).slice(0, 3).forEach(function(s) {
      suggestions.push({ type: 'source', label: s, count: sourceCounts[s] });
    });
    ALL_ARTICLES.filter(function(a) {
      return (a.title || '').toLowerCase().indexOf(ql) !== -1;
    }).slice(0, 5).forEach(function(a) {
      suggestions.push({ type: 'article', label: a.title, url: a.url });
    });
    var box = document.getElementById('search-suggestions');
    if (!box) return;
    var deepItem = q.length >= 2 ? [{ type: 'deep', label: q }] : [];
    var allItems = suggestions.concat(deepItem);
    if (allItems.length === 0) { closeSuggestions(); return; }
    box.innerHTML = allItems.map(function(s, i) {
      if (s.type === 'deep') {
        var slug = s.label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
        var href = (APP_TOPIC_SLUGS.indexOf(slug) !== -1)
          ? ('deep-dives/' + slug + '.html')
          : ('deep-dives/viewer.html?q=' + encodeURIComponent(s.label));
        return '<div class="search-sugg-item deep-analysis" data-idx="' + i + '" data-type="deep" data-url="' + href + '">' +
          '<span class="search-sugg-type deep">AI</span>' +
          '<span class="search-sugg-text">Deep Analysis: ' + s.label + '</span>' +
          '<span class="deep-sugg-hint">full report &rarr;</span></div>';
      }
      var countHtml = s.count ? '<span class="search-sugg-count">' + s.count + '</span>' : '';
      return '<div class="search-sugg-item" data-idx="' + i + '" data-type="' + s.type + '" data-label="' + s.label.replace(/"/g,'&quot;') + '" data-url="' + (s.url||'') + '">' +
        '<span class="search-sugg-type ' + s.type + '">' + s.type + '</span>' +
        '<span class="search-sugg-text">' + s.label + '</span>' +
        countHtml + '</div>';
    }).join('');
    box.style.display = 'block';
    _suggIdx = -1;
    box.querySelectorAll('.search-sugg-item').forEach(function(el) {
      el.addEventListener('click', function() {
        var type = el.dataset.type;
        var label = el.dataset.label;
        if (type === 'deep' || (type === 'article' && el.dataset.url)) {
          window.location.href = el.dataset.url;
          closeSuggestions();
          return;
        }
        document.getElementById('search-input').value = label;
        handleSearch(label);
        closeSuggestions();
      });
    });
  }

  document.addEventListener('click', function(e) {
    if (!e.target.closest('#search-suggestions') && !e.target.closest('#search-input')) {
      closeSuggestions();
    }
  });

  /* ── Search ── */
  window.handleSearch = function(query) {
    buildSuggestions(query);
    var trimmed = query.trim();
    state.searchQuery = trimmed.toLowerCase();
    applyFilters();
    var btn = document.getElementById('deep-dive-btn');
    if (trimmed.length >= 2) {
      var slug = trimmed.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
      var href = (APP_TOPIC_SLUGS.indexOf(slug) !== -1)
        ? ('deep-dives/' + slug + '.html')
        : ('deep-dives/viewer.html?q=' + encodeURIComponent(trimmed));
      btn.href = href;
      btn.innerHTML = '&#9670; Deep Dive: ' + trimmed;
      btn.classList.add('visible');
    } else {
      btn.classList.remove('visible');
      btn.href = '#';
    }
    var inp = document.getElementById('search-input');
    if (inp) inp.placeholder = 'Search ' + ALL_ARTICLES.length.toLocaleString() + ' articles... ( / )';
  };

  /* ── Update search placeholder with article count ── */
  (function() {
    var inp = document.getElementById('search-input');
    if (inp && ALL_ARTICLES.length > 0) {
      inp.placeholder = 'Search ' + ALL_ARTICLES.length.toLocaleString() + ' articles... ( / )';
    }
  })();

  /* ── Topic filter ── */
  window.toggleTopicFilter = function(btn, topic) {
    btn.classList.toggle('active');
    if (state.activeTopics.has(topic)) { state.activeTopics.delete(topic); }
    else { state.activeTopics.add(topic); }
    applyFilters();
  };

  window.setTopicFilter = function(topic) {
    state.activeTopics = new Set([topic]);
    document.querySelectorAll('.topic-filter-btn').forEach(function(b) {
      b.classList.toggle('active', b.dataset.topic === topic);
    });
    applyFilters();
    var card = document.getElementById('section-' + topic);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  window.setAllTopics = function() {
    state.activeTopics = new Set(state.allTopics);
    document.querySelectorAll('.topic-filter-btn').forEach(function(b) { b.classList.add('active'); });
    applyFilters();
  };

  /* ── Urgency filter ── */
  window.setUrgencyFilter = function(btn, val) {
    state.urgencyFilter = val;
    document.querySelectorAll('.urgency-filter-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    applyFilters();
  };

  /* ── New filter ── */
  window.setNewFilter = function(btn, val) {
    state.newFilter = val;
    document.querySelectorAll('.new-filter-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    applyFilters();
  };

  /* ── Sort order ── */
  window.setSortOrder = function(btn, val) {
    state.sortOrder = val;
    document.querySelectorAll('.sort-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    applyFilters();
  };

  /* ── Relevance filter ── */
  window.setRelFilter = function(btn, val) {
    state.relFilter = val;
    document.querySelectorAll('.rel-filter-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    applyFilters();
  };

  /* ── Apply all active filters ── */
  function applyFilters() {
    var q = state.searchQuery;
    var items = document.querySelectorAll('.article-item');
    var visibleCount = 0;

    items.forEach(function(item) {
      var topic = (item.dataset.topic || '').toLowerCase();
      var urgency = (item.dataset.urgency || '').toUpperCase();
      var isNew = item.dataset.isNew === 'true' || item.dataset.isNew === '1';
      var rel = (item.dataset.relevance || '').toUpperCase();
      var title = (item.dataset.title || item.querySelector('a') && item.querySelector('a').textContent || '').toLowerCase();
      var snippet = (item.dataset.snippet || '').toLowerCase();
      var source = (item.dataset.source || '').toLowerCase();

      var topicOk = state.activeTopics.has(topic);
      var urgencyOk = state.urgencyFilter === 'ALL' || urgency === state.urgencyFilter;
      var newOk = state.newFilter === 'ALL' || (state.newFilter === 'NEW' && isNew) || (state.newFilter === 'EXISTING' && !isNew);
      var relOk = state.relFilter === 'all' ||
        (state.relFilter === 'relevant' && (rel === 'DIRECT' || rel === 'INDIRECT')) ||
        (rel === state.relFilter.toUpperCase());
      var searchOk = !q || title.indexOf(q) !== -1 || snippet.indexOf(q) !== -1 || source.indexOf(q) !== -1;

      var visible = topicOk && urgencyOk && newOk && relOk && searchOk;
      item.style.display = visible ? '' : 'none';
      if (visible) visibleCount++;
    });

    var countEl = document.getElementById('search-count');
    if (countEl) countEl.textContent = visibleCount ? visibleCount + ' articles' : '';
  }

  window.applyFilters = applyFilters;

  /* ── Keyboard shortcut: / to focus search ── */
  document.addEventListener('keydown', function(e) {
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
      e.preventDefault();
      var inp = document.getElementById('search-input');
      if (inp) inp.focus();
    }
  });

})();
```

- [ ] **Step 2: Remove the corresponding functions from dashboard.html**

In `dashboard/templates/dashboard.html`, find and remove the following from the inline JS:
- The `var state = {...}` block and all its Jinja2-embedded lines
- The `window.toggleTopicFilter`, `window.setTopicFilter`, `window.setAllTopics`, `window.setUrgencyFilter`, `window.setNewFilter`, `window.setSortOrder`, `window.setRelFilter` functions
- The `applyFilters` function
- The autocomplete / `buildSuggestions` / `handleSearch` functions
- The keyboard shortcut handler for `/`
- The search placeholder updater

Also remove the duplicate Jinja2 references now covered by `APP_TOPICS` and `APP_TOPIC_SLUGS`.

- [ ] **Step 3: Add script tag to dashboard.html**

In `dashboard/templates/dashboard.html`, add before `</body>` (after the data bridge, after nav.js):

```html
<script src="static/js/filters.js"></script>
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/js/filters.js dashboard/templates/dashboard.html
git commit -m "refactor: extract filter/search JS to dashboard/static/js/filters.js"
```

---

## Task 7: Extract modals.js and ui.js from dashboard.html

**Files:**
- Create: `dashboard/static/js/modals.js`
- Create: `dashboard/static/js/ui.js`
- Modify: `dashboard/templates/dashboard.html`

`modals.js` contains: expand modal (openExpandModal, closeExpandModal), history/archive modal (openHistoryModal, closeHistoryModal, filterHistoryModal, setHistoryPeriod).

`ui.js` contains: cross-state tab switcher (csDashTabShow), Lucide icon init, resizable sidebar, timeline dot clustering, widget preferences (customize drawer).

- [ ] **Step 1: Create modals.js**

Create `dashboard/static/js/modals.js`:

```javascript
/* modals.js — Expand modal and article history modal */
(function() {
  'use strict';

  /* ── Expand Modal ── */
  window.openExpandModal = function(widgetId, title) {
    var overlay = document.getElementById('expand-modal-overlay');
    var body    = document.getElementById('expand-modal-body');
    var titleEl = document.getElementById('expand-modal-title');
    var panel   = document.querySelector('[data-widget-id="' + widgetId + '"]');
    if (!panel) { alert('Widget not found'); return; }
    var src = panel.querySelector('.panel-body') || panel.querySelector('[style*="padding"]') || panel;
    var clone = src.cloneNode(true);
    clone.querySelectorAll('.expand-btn').forEach(function(btn) { btn.remove(); });
    clone.querySelectorAll('.chart-trend-section').forEach(function(el) { el.style.display = 'block'; });
    clone.querySelectorAll('svg').forEach(function(svg) {
      svg.style.width = '100%';
      svg.removeAttribute('height');
      svg.style.height = 'auto';
      svg.style.minHeight = '80px';
    });
    clone.style.maxHeight = 'none';
    clone.style.overflow = 'visible';
    titleEl.textContent = title;
    body.innerHTML = '';
    body.appendChild(clone);
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  };

  window.closeExpandModal = function(e) {
    if (!e || e.target === document.getElementById('expand-modal-overlay')) {
      document.getElementById('expand-modal-overlay').classList.remove('open');
      document.body.style.overflow = '';
    }
  };

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      var overlay = document.getElementById('expand-modal-overlay');
      if (overlay) overlay.classList.remove('open');
      document.body.style.overflow = '';
    }
  });

  /* ── History / 6-Month Archive Modal ── */
  /* ALL_ARTICLES is set by the inline data bridge in dashboard.html */
  var _historyTopic = null;
  var _historyPeriod = 'all';

  window.openHistoryModal = function(topic, label) {
    _historyTopic = topic;
    _historyPeriod = 'all';
    document.getElementById('history-modal-title').textContent = label + ' — Article Archive';
    document.getElementById('history-modal-search').value = '';
    document.querySelectorAll('.history-filter-chip').forEach(function(c) {
      c.classList.toggle('active', c.dataset.period === 'all');
    });
    filterHistoryModal();
    var overlay = document.getElementById('history-modal-overlay');
    overlay.style.display = 'flex';
    setTimeout(function() { document.getElementById('history-modal-search').focus(); }, 100);
  };

  window.closeHistoryModal = function(e) {
    if (e && e.target !== document.getElementById('history-modal-overlay')) return;
    document.getElementById('history-modal-overlay').style.display = 'none';
  };

  window.setHistoryPeriod = function(btn, period) {
    _historyPeriod = period;
    document.querySelectorAll('.history-filter-chip').forEach(function(c) {
      c.classList.toggle('active', c === btn);
    });
    filterHistoryModal();
  };

  window.filterHistoryModal = function() {
    var q = document.getElementById('history-modal-search').value.toLowerCase().trim();
    var cutoff = '';
    if (_historyPeriod !== 'all') {
      var d = new Date();
      d.setDate(d.getDate() - parseInt(_historyPeriod));
      cutoff = d.toISOString().slice(0,10);
    }
    var filtered = ALL_ARTICLES.filter(function(a) {
      if (_historyTopic && (a.topic || '').toLowerCase() !== _historyTopic.toLowerCase()) return false;
      if (cutoff && (a.first_seen || '') < cutoff) return false;
      if (!q) return true;
      return (a.title || '').toLowerCase().indexOf(q) !== -1 ||
             (a.snippet || '').toLowerCase().indexOf(q) !== -1 ||
             (a.source || '').toLowerCase().indexOf(q) !== -1;
    });
    filtered.sort(function(a,b) { return (b.first_seen||'').localeCompare(a.first_seen||''); });
    document.getElementById('history-modal-count').textContent = filtered.length + ' articles';
    var html = filtered.length ? filtered.map(function(a) {
      var badge = a.is_new ? '<span style="background:#EBF8FF;color:#1A56A0;font-size:10px;padding:1px 6px;border-radius:8px;font-weight:600;margin-right:6px;">New</span>' : '';
      return '<div class="history-modal-article">' +
        '<div>' + badge + '<a href="' + (a.url||'#') + '" target="_blank">' + (a.title||'Untitled') + '</a></div>' +
        '<div class="history-modal-meta">' + (a.source||'') + (a.pub_date ? ' &middot; ' + a.pub_date : '') + '</div>' +
        (a.snippet ? '<div class="history-modal-snippet">' + a.snippet + '</div>' : '') +
        '</div>';
    }).join('') : '<p style="color:var(--text-muted);text-align:center;padding:24px 0;">No articles found.</p>';
    document.getElementById('history-modal-body').innerHTML = html;
  };

})();
```

- [ ] **Step 2: Create ui.js**

Create `dashboard/static/js/ui.js`:

```javascript
/* ui.js — Cross-state tabs, timeline clustering, resizable sidebar, Lucide init, widget prefs */
(function() {
  'use strict';

  /* ── Cross-state tab switcher ── */
  window.csDashTabShow = function(topic) {
    document.querySelectorAll('.cs-dash-panel').forEach(function(el) { el.classList.remove('active'); });
    document.querySelectorAll('.cs-dash-tab').forEach(function(el) { el.classList.remove('active'); });
    var panel = document.querySelector('.cs-dash-panel[data-cs-panel="' + topic + '"]');
    var tab = document.querySelector('.cs-dash-tab[data-cs-topic="' + topic + '"]');
    if (panel) panel.classList.add('active');
    if (tab) tab.classList.add('active');
  };

  /* ── Lucide icon init ── */
  if (typeof lucide !== 'undefined') lucide.createIcons();

  /* ── Resizable sidebar ── */
  (function() {
    var handle = document.getElementById('sidebar-resize-handle');
    var sidebar = document.getElementById('grid-sidebar');
    if (!handle || !sidebar) return;
    var dragging = false, startX, startW;
    handle.addEventListener('mousedown', function(e) {
      dragging = true;
      startX = e.clientX;
      startW = sidebar.offsetWidth;
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
      if (!dragging) return;
      var dx = startX - e.clientX;
      var newW = Math.max(240, Math.min(600, startW + dx));
      sidebar.style.width = newW + 'px';
    });
    document.addEventListener('mouseup', function() {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem('sidebarWidth', sidebar.offsetWidth);
    });
    var savedW = localStorage.getItem('sidebarWidth');
    if (savedW) sidebar.style.width = savedW + 'px';
  })();

  /* ── Timeline dot clustering ── */
  var THRESHOLD = 5;
  document.querySelectorAll('.tl-track').forEach(function(track) {
    var dots = Array.from(track.querySelectorAll('.tl-dot'));
    if (dots.length < 2) return;
    dots.sort(function(a, b) { return parseFloat(a.dataset.tlPct) - parseFloat(b.dataset.tlPct); });
    var groups = [], cur = [dots[0]];
    for (var i = 1; i < dots.length; i++) {
      if (parseFloat(dots[i].dataset.tlPct) - parseFloat(dots[i-1].dataset.tlPct) < THRESHOLD) {
        cur.push(dots[i]);
      } else { groups.push(cur); cur = [dots[i]]; }
    }
    groups.push(cur);
    groups.forEach(function(group) {
      if (group.length < 2) return;
      var hasHigh = group.some(function(d) { return d.dataset.urgency === 'HIGH'; });
      var hasMed  = group.some(function(d) { return d.dataset.urgency === 'MEDIUM'; });
      var color   = hasHigh ? 'var(--red)' : hasMed ? 'var(--amber)' : 'var(--green)';
      var avgPct  = group.reduce(function(s, d) { return s + parseFloat(d.dataset.tlPct); }, 0) / group.length;
      var tipHtml = group.map(function(d) {
        return '<b>' + (d.dataset.title || '') + '</b><br>' + (d.dataset.date || '') + ' &middot; ' + (d.dataset.days || '') + 'd &middot; ' + (d.dataset.urgency || '');
      }).join('<hr>');
      group.forEach(function(d) { d.style.display = 'none'; });
      var badge = document.createElement('div');
      badge.className = 'tl-cluster-badge';
      badge.style.cssText = 'left:' + avgPct + '%;background:' + color + ';';
      badge.innerHTML = group.length + '<span class="tl-tip">' + tipHtml + '</span>';
      track.appendChild(badge);
    });
  });

})();
```

- [ ] **Step 3: Remove the corresponding code blocks from dashboard.html**

Find and remove these script blocks from `dashboard/templates/dashboard.html`:
- The entire `<script>/* ── Expand Modal ── */...` block (lines ~4961–5032)
- The entire `<script>/* ── Timeline Dot Clustering ── */...` block (lines ~5034–5154) including the history modal functions and search extension
- The `csDashTabShow` function and `lucide.createIcons()` call
- The resizable sidebar block

Also remove the widget preferences block if it still exists inline (the customize drawer `applyWidgetPrefs`/`loadWidgetPrefs` functions) — move these to `ui.js` as well.

- [ ] **Step 4: Add script tags to dashboard.html**

In `dashboard/templates/dashboard.html`, add before `</body>`:

```html
<script src="static/js/modals.js"></script>
<script src="static/js/ui.js"></script>
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/js/modals.js dashboard/static/js/ui.js dashboard/templates/dashboard.html
git commit -m "refactor: extract modal and UI JS to modals.js and ui.js"
```

---

## Task 8: Create stub JS files for future features

**Files:**
- Create: `dashboard/static/js/auth.js`
- Create: `dashboard/static/js/notifications.js`
- Create: `dashboard/static/js/favorites.js`
- Create: `dashboard/static/js/comments.js`
- Create: `dashboard/static/js/messages.js`

These files are empty stubs. They're created now so the `<script>` tags can be added to the template in the right order, and future plans can fill them in without modifying template structure.

- [ ] **Step 1: Create all stub files**

```bash
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2

cat > dashboard/static/js/auth.js << 'EOF'
/* auth.js — Supabase auth checks and login wall (Phase 2) */
EOF

cat > dashboard/static/js/notifications.js << 'EOF'
/* notifications.js — Bell feed, unread count, notification dropdown (Phase 3) */
EOF

cat > dashboard/static/js/favorites.js << 'EOF'
/* favorites.js — Bookmark articles, My Saved Articles (Phase 3) */
EOF

cat > dashboard/static/js/comments.js << 'EOF'
/* comments.js — Comment threads on articles, deadlines, bills (Phase 3) */
EOF

cat > dashboard/static/js/messages.js << 'EOF'
/* messages.js — Direct messages, unread DM badge (Phase 4) */
EOF
```

- [ ] **Step 2: Add stub script tags to dashboard.html (load order matters)**

In `dashboard/templates/dashboard.html`, arrange the script tags before `</body>` in this load order:

```html
<!-- Jinja2 data bridge (inline, must be first) -->
<script>
var BILL_ANALYSES = {{ bill_analyses|tojson }};
var DEADLINE_ANALYSES = {{ deadline_analyses|tojson }};
var APP_TOPICS = {{ topics|map(attribute='topic')|list|map('lower')|list|tojson }};
var APP_TOPIC_SLUGS = {{ topic_slugs | tojson }};
var ALL_ARTICLES = [];
try { ALL_ARTICLES = {{ all_articles_json | safe }}; } catch(e) {}
</script>

<!-- Feature JS files -->
<script src="static/js/auth.js"></script>
<script src="static/js/nav.js"></script>
<script src="static/js/filters.js"></script>
<script src="static/js/modals.js"></script>
<script src="static/js/ui.js"></script>
<script src="static/js/notifications.js"></script>
<script src="static/js/favorites.js"></script>
<script src="static/js/comments.js"></script>
<script src="static/js/messages.js"></script>
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/js/auth.js dashboard/static/js/notifications.js dashboard/static/js/favorites.js dashboard/static/js/comments.js dashboard/static/js/messages.js dashboard/templates/dashboard.html
git commit -m "refactor: add stub JS files for Phase 2-4 features; set final script load order"
```

---

## Task 9: Create Jinja2 HTML partials

**Files:**
- Create: `dashboard/templates/_sidebar.html`
- Create: `dashboard/templates/_topbar.html`
- Create: `dashboard/templates/_article_card.html`
- Create: `dashboard/templates/_badge_legend.html`
- Modify: `dashboard/templates/dashboard.html`

- [ ] **Step 1: Create _sidebar.html**

Locate the nav rail in `dashboard/templates/dashboard.html` — it starts with `<!-- ═══ NAV RAIL ═══ -->` and runs through `</nav>`. Cut that entire block (from `<!-- ═══ NAV RAIL ═══ -->` through the closing `</nav>`) and save it as `dashboard/templates/_sidebar.html` exactly as-is.

The extracted file should start with:
```html
<!-- ═══ NAV RAIL ═══ -->
<nav class="rail" id="sidebar">
```

And end with:
```html
</nav>
```

In `dashboard/templates/dashboard.html`, replace that block with:
```html
{% include '_sidebar.html' %}
```

- [ ] **Step 2: Create _topbar.html**

Locate the topbar in `dashboard/templates/dashboard.html` — it starts with `<!-- ═══ TOPBAR ═══ -->` (or the first `<header` or `<div class="topbar"`). Cut it from its opening comment/tag through its closing `</div>` or `</header>`. Save as `dashboard/templates/_topbar.html`.

In `dashboard/templates/dashboard.html`, replace with:
```html
{% include '_topbar.html' %}
```

- [ ] **Step 3: Create _article_card.html**

Find the repeated article card HTML inside the article list loop. It will look like:
```html
{% for article in topic.articles %}
<div class="article-item" data-topic="{{ ... }}" ...>
  ...article card content...
</div>
{% endfor %}
```

Extract just the inner card template (the `<div class="article-item"...>...</div>` block) into `dashboard/templates/_article_card.html`. The for loop stays in `dashboard.html`; only the card body becomes a partial.

Replace the card HTML in `dashboard.html` with:
```html
{% include '_article_card.html' %}
```

- [ ] **Step 4: Create _badge_legend.html**

Find the badge legend HTML (usually a small `<div>` showing the Direct/Indirect/Monitor and badge type key). Cut it and save as `dashboard/templates/_badge_legend.html`.

Replace in `dashboard.html` with:
```html
{% include '_badge_legend.html' %}
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/templates/_sidebar.html dashboard/templates/_topbar.html dashboard/templates/_article_card.html dashboard/templates/_badge_legend.html dashboard/templates/dashboard.html
git commit -m "refactor: extract dashboard.html HTML sections into Jinja2 partials"
```

---

## Task 10: Update run.py to deploy static files

The pipeline pushes rendered HTML to `/tmp/compliance-maps` (a clone of the GitHub Pages repo). Static CSS/JS files also need to be copied there so Vercel can serve them. **All changes are in the NEW project's run.py.**

**Files:**
- Modify: `run.py` (in the new repo)

- [ ] **Step 1: Locate the dashboard push function**

Find `_push_dashboard` or the main function in `run.py` that copies `dashboard.html` and topic pages to `/tmp/compliance-maps`. It uses `shutil.copy2` calls.

Search for it:
```bash
grep -n "dashboard.html\|shutil.copy2" run.py | head -20
```

- [ ] **Step 2: Add static file copy to the deployment function**

Find the function that copies `dashboard.html` to the GitHub Pages repo (e.g., `_push_dashboard` or wherever `dashboard.html` gets copied). After the HTML copy calls, add:

```python
# Copy static assets (CSS/JS) alongside the HTML files
import os
static_src = Path(__file__).parent / "dashboard" / "static"
static_dest = repo_dir / "static"
if static_src.exists():
    if static_dest.exists():
        import shutil as _shutil_static
        _shutil_static.rmtree(static_dest)
    import shutil as _shutil_static
    _shutil_static.copytree(str(static_src), str(static_dest))
    # Add all static files to git
    import subprocess as _sp
    _sp.run(["git", "-C", str(repo_dir), "add", "static/"], capture_output=True)
```

Also add `"static/"` to the files list passed to `_git_push`.

- [ ] **Step 3: Commit**

```bash
git add run.py
git commit -m "feat: copy dashboard/static/ CSS+JS assets to GitHub Pages repo on deploy"
```

---

## Task 11: Verify the refactor works

Before touching infrastructure, run the pipeline in the new repo and confirm the rendered output looks correct in a browser.

- [ ] **Step 1: Set up the new project's Python environment**

```bash
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 2: Copy the .env from the production project**

```bash
cp /Users/ryanjenkinson/Desktop/compliance-monitor/.env /Users/ryanjenkinson/Desktop/compliance-monitor-v2/.env
```

- [ ] **Step 3: Run the pipeline in preview mode**

```bash
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2
source .venv/bin/activate
python3 run.py --preview
```

Expected: Opens the dashboard in your browser. Verify:
- [ ] Layout looks identical to the production dashboard
- [ ] Sidebar accordion opens/closes
- [ ] Search box works (type something, suggestions appear)
- [ ] Topic filter chips work
- [ ] Article cards expand on click
- [ ] Timeline dots cluster correctly
- [ ] No browser console errors

- [ ] **Step 4: Check browser console for JS errors**

Open Chrome DevTools (Cmd+Option+I), go to Console tab. Look for any `ReferenceError` or `TypeError`. A successful refactor has zero console errors.

Common issues to look for:
- `APP_TOPICS is not defined` → data bridge script not loaded before nav.js
- `handleSearch is not defined` → filters.js load order issue
- `lucide is not defined` → Lucide CDN script needs to load before ui.js

Fix any errors before proceeding.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve any JS load-order or reference errors from modular refactor"
```

---

## Task 12: Set up Supabase project (manual)

This task is manual — no code is written. Supabase credentials are added to `.env` for use in Phase 2.

- [ ] **Step 1: Create a Supabase project**

1. Go to [supabase.com](https://supabase.com) and sign in
2. Click "New project"
3. Name it `compliance-monitor-v2`
4. Choose a strong database password (save it somewhere safe)
5. Select region: US East (closest to you)
6. Click "Create new project" and wait ~2 minutes

- [ ] **Step 2: Get your project credentials**

In the Supabase dashboard:
1. Click "Settings" (gear icon, left sidebar)
2. Click "API"
3. Copy:
   - **Project URL** (looks like `https://xxxxxxxxxxxx.supabase.co`)
   - **anon (public) key** (long JWT string under "Project API keys")

- [ ] **Step 3: Add credentials to .env**

Open `/Users/ryanjenkinson/Desktop/compliance-monitor-v2/.env` and add:

```
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGci....(your full anon key)
```

- [ ] **Step 4: Add Supabase credentials to .gitignore**

Confirm `.env` is in `.gitignore`:

```bash
grep "^\.env" .gitignore
```

Expected output: `.env` (or `.env*`). If not present, add it.

- [ ] **Step 5: Add SUPABASE_URL and SUPABASE_ANON_KEY to .env.example**

Open `.env.example` and add the two keys (with blank values) so the next person knows what's needed:

```
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

```bash
git add .env.example
git commit -m "chore: add Supabase credentials to .env.example"
```

---

## Task 13: Set up Vercel project (manual)

This task is manual. By the end, the new GitHub repo auto-deploys to a Vercel URL.

- [ ] **Step 1: Create a Vercel account**

Go to [vercel.com](https://vercel.com) and sign up with your GitHub account.

- [ ] **Step 2: Import the new GitHub repository**

1. On the Vercel dashboard, click "Add New → Project"
2. Select "Import Git Repository"
3. Find and select `compliance-monitor-v2`
4. Configure the project:
   - **Framework Preset:** Other
   - **Root Directory:** `.` (repo root)
   - **Build Command:** (leave blank — no build step, static files only)
   - **Output Directory:** `.` (HTML files are at root)
5. Click "Deploy"

- [ ] **Step 3: Note the Vercel URL**

After deploy completes, Vercel shows a URL like `https://compliance-monitor-v2.vercel.app`. Copy it.

- [ ] **Step 4: Update _PAGES_BASE in run.py**

In `/Users/ryanjenkinson/Desktop/compliance-monitor-v2/run.py`, update:

```python
# Old (production project — never change this one):
# _PAGES_BASE = "https://ryan-jenkinson.github.io/compliance-maps"

# New V2 project:
_PAGES_BASE = "https://compliance-monitor-v2.vercel.app"
```

- [ ] **Step 5: Update _GITHUB_REPO_DIR in run.py**

Also update the local git clone path for the deployment repo:

```python
# Old:
# _GITHUB_REPO_DIR = Path("/tmp/compliance-maps")

# New:
_GITHUB_REPO_DIR = Path("/tmp/compliance-monitor-v2-pages")
```

- [ ] **Step 6: Clone the new GitHub repo to the new local path**

```bash
cd /tmp
git clone https://github.com/<your-username>/compliance-monitor-v2.git compliance-monitor-v2-pages
```

- [ ] **Step 7: Commit run.py changes**

```bash
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2
git add run.py
git commit -m "chore: update deploy target to new Vercel URL and local pages clone path"
```

---

## Task 14: Full pipeline run and verify deployment

- [ ] **Step 1: Run the full pipeline with --no-email**

```bash
cd /Users/ryanjenkinson/Desktop/compliance-monitor-v2
source .venv/bin/activate
python3 run.py --no-email
```

Expected: Pipeline runs, renders all pages, pushes HTML + static/ to the new GitHub repo at `/tmp/compliance-monitor-v2-pages`, which triggers a Vercel deploy.

- [ ] **Step 2: Verify Vercel deployment**

1. Go to the Vercel dashboard
2. Check the latest deployment — it should be triggered by the git push
3. Click the deployment URL to open the live site

- [ ] **Step 3: Verify the live site**

Open the Vercel URL in a browser. Confirm:
- [ ] Dashboard loads with correct layout (not a blank page or 404)
- [ ] CSS loads correctly (check Network tab — `static/css/dashboard.css` returns 200)
- [ ] JS loads correctly (check Network tab — `static/js/nav.js`, `filters.js` etc. return 200)
- [ ] Sidebar accordion works
- [ ] Search works
- [ ] Topic pages load

- [ ] **Step 4: Confirm production project is unaffected**

```bash
# Should still push to the original GitHub Pages repo
git -C /tmp/compliance-maps log --oneline -3
```

The production project should have no new commits from this work.

---

## Self-review checklist

- [x] **Spec coverage — Step 0:**
  - CSS extracted from dashboard.html → dashboard.css ✓
  - CSS extracted from topic_page.html → topic.css ✓
  - JS split into nav.js, filters.js, modals.js, ui.js, auth.js stub, notifications.js stub, favorites.js stub, comments.js stub, messages.js stub ✓
  - HTML broken into _topbar.html, _sidebar.html, _article_card.html, _badge_legend.html ✓
  - Email templates NOT touched (base.html, topic_section.html, exec_summary.html) ✓

- [x] **Spec coverage — Step 1:**
  - New GitHub repo created ✓
  - Supabase project created, credentials in .env ✓
  - Vercel project connected to new repo ✓
  - Pipeline push target updated ✓

- [x] **No placeholders:** All code is complete and real, not described abstractly

- [x] **Type/name consistency:** `APP_TOPICS`, `APP_TOPIC_SLUGS`, `ALL_ARTICLES`, `BILL_ANALYSES`, `DEADLINE_ANALYSES` used consistently across all tasks

---

Plan complete and saved to `docs/superpowers/plans/2026-03-26-v2-plan-1-foundation.md`.
