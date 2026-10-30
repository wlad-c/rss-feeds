/* Pocket Casts listening explore app */
(() => {
  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  /* Apple system / SF chart palette — categorical hues stay distinct */
  const THEME_KEY = "listening-log-theme";
  const METRIC_KEY = "listening-log-metric";
  const COLORS = {
    ink: "#1C1C1E",
    muted: "#8E8E93",
    blue: "#007AFF",
    amber: "#FF9500",
    teal: "#30B0C7",
    vermillion: "#FF3B30",
    sky: "#64D2FF",
    olive: "#34C759",
    rose: "#FF2D55",
    rust: "#FF9F0A",
    slate: "#8E8E93",
    navy: "#5856D6",
  };
  const COLORS_DARK = {
    ink: "#F5F5F7",
    muted: "#98989D",
    blue: "#0A84FF",
    amber: "#FF9F0A",
    teal: "#40CBE0",
    vermillion: "#FF453A",
    sky: "#64D2FF",
    olive: "#30D158",
    rose: "#FF375F",
    rust: "#FFD60A",
    slate: "#8E8E93",
    navy: "#5E5CE6",
  };
  const CATEGORICAL = [
    COLORS.blue,
    COLORS.amber,
    COLORS.teal,
    COLORS.vermillion,
    COLORS.sky,
    COLORS.olive,
    COLORS.rose,
    COLORS.rust,
    COLORS.navy,
    COLORS.slate,
  ];
  const CATEGORICAL_DARK = [
    COLORS_DARK.blue,
    COLORS_DARK.amber,
    COLORS_DARK.teal,
    COLORS_DARK.vermillion,
    COLORS_DARK.sky,
    COLORS_DARK.olive,
    COLORS_DARK.rose,
    COLORS_DARK.rust,
    COLORS_DARK.navy,
    COLORS_DARK.slate,
  ];
  const state = {
    agg: null,
    episodes: null,
    podcasts: null,
    countriesDoc: null,
    themesDoc: null,
    episodeThemes: null,
    episodeThemeWeights: null,
    notes: null,
    themeById: {},
    activeTheme: "",
    focusedParentId: "",
    themeMatchView: "podcasts", // "podcasts" | "episodes"
    themeMatchPage: 0,
    themeMatchPageSize: 25,
    _themeMatchThemeId: "",
    _themeShowsThemeId: "",
    metric: "episodes", // "episodes" | "hours"
    chartPeriod: {
      from: "",
      to: "",
      preset: "all",
      country: "",
      podcast: "",
      theme: "",
      status: "",
      q: "",
    },
    charts: {},
    barReveal: {},
    page: 0,
    pageSize: 40,
    _chartStats: null,
    _chartStatsKey: "",
    _chartStatsCache: null,
    _localStats: null,
    _periodIndex: null,
    /* Performance indexes — filled once after load */
    _epHours: null,
    _epCountry: null,
    _epHay: null,
    _epHour: null,
    _epWeekday: null,
    _epThemeHas: null,
    _countryOptionsHtml: "",
    _podcastOptionsHtml: "",
    _notesCoverage: null,
    _matchedCache: null,
    _matchedCacheKey: "",
    _renderGen: 0,
    _renderTimer: 0,
  };
  const BAR_PAGE = 12;
  const MONTH_OPTIONS = [
    ["01", "January"],
    ["02", "February"],
    ["03", "March"],
    ["04", "April"],
    ["05", "May"],
    ["06", "June"],
    ["07", "July"],
    ["08", "August"],
    ["09", "September"],
    ["10", "October"],
    ["11", "November"],
    ["12", "December"],
  ];
  const MONTH_NAME = Object.fromEntries(MONTH_OPTIONS);
  const MONTH_SHORT = Object.fromEntries(
    MONTH_OPTIONS.map(([num, name]) => [num, name.slice(0, 3)])
  );

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
  const JUMP_TARGETS = ["trends", "shows", "themes", "patterns", "explorePanel"];
  const TAB_MQ = window.matchMedia("(max-width: 860px)");
  let activeTabId = "trends";
  let sectionScrollSpy = null;

  function isTabMode() {
    return TAB_MQ.matches;
  }

  function setActiveJump(id) {
    $$("[data-jump]").forEach((a) => {
      const on = a.getAttribute("data-jump") === id;
      a.classList.toggle("is-active", on);
      if (a.getAttribute("role") === "tab") {
        a.setAttribute("aria-selected", on ? "true" : "false");
      }
      if (on) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  }

  function resizeAllCharts() {
    Object.values(state.charts).forEach((chart) => {
      try {
        chart?.resize?.();
      } catch (_) {}
    });
  }

  function showTab(id, { scrollTop = true } = {}) {
    if (!JUMP_TARGETS.includes(id)) id = "trends";
    activeTabId = id;
    document.body.classList.toggle("tab-mode", isTabMode());
    document.body.dataset.activeTab = id;
    JUMP_TARGETS.forEach((tid) => {
      const panel = document.getElementById(tid);
      if (!panel) return;
      const on = tid === id;
      panel.classList.toggle("is-tab-active", on);
      panel.setAttribute("aria-hidden", isTabMode() && !on ? "true" : "false");
    });
    setActiveJump(id);
    if (isTabMode() && scrollTop) {
      window.scrollTo({ top: 0, behavior: "auto" });
    }
    requestAnimationFrame(() => {
      resizeAllCharts();
      requestAnimationFrame(resizeAllCharts);
    });
  }

  function goToSection(id) {
    if (isTabMode()) {
      showTab(id);
      return;
    }
    setActiveJump(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function syncTabMode() {
    const on = isTabMode();
    document.body.classList.toggle("tab-mode", on);
    if (on) {
      sectionScrollSpy?.disconnect?.();
      sectionScrollSpy = null;
      showTab(activeTabId, { scrollTop: false });
      return;
    }
    JUMP_TARGETS.forEach((tid) => {
      const panel = document.getElementById(tid);
      if (!panel) return;
      panel.classList.add("is-tab-active");
      panel.setAttribute("aria-hidden", "false");
    });
    delete document.body.dataset.activeTab;
    setActiveJump(activeTabId);
    requestAnimationFrame(resizeAllCharts);
  }

  const fmt = (n) => Number(n || 0).toLocaleString();
  const fmtHours = (h) => {
    const n = Number(h) || 0;
    if (n >= 100) return Math.round(n).toLocaleString();
    return (Math.round(n * 10) / 10).toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 1,
    });
  };
  const fmtMetric = (n) => (metricIsHours() ? fmtHours(n) : fmt(n));
  const escapeHtml = (s) =>
    String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");

  function metricIsHours() {
    return state.metric === "hours";
  }

  function metricValueLabel() {
    return metricIsHours() ? "Hours" : "Episodes";
  }

  function parseDurHours(dur) {
    if (!dur) return 0;
    const parts = String(dur)
      .split(":")
      .map((x) => Number(x));
    if (!parts.length || parts.some((n) => !Number.isFinite(n))) return 0;
    let sec = 0;
    if (parts.length === 3) sec = parts[0] * 3600 + parts[1] * 60 + parts[2];
    else if (parts.length === 2) sec = parts[0] * 60 + parts[1];
    else sec = parts[0];
    return sec > 0 ? sec / 3600 : 0;
  }

  function readStoredMetric() {
    try {
      const v = localStorage.getItem(METRIC_KEY);
      if (v === "hours" || v === "episodes") return v;
    } catch (_) {}
    return "episodes";
  }

  function applyMetric(metric, { persist = true, rerender = true } = {}) {
    const next = metric === "hours" ? "hours" : "episodes";
    state.metric = next;
    if (persist) {
      try {
        localStorage.setItem(METRIC_KEY, next);
      } catch (_) {}
    }
    syncMetricToggle();
    updateMetricLabels();
    if (rerender && state.agg) {
      state._localStats = null;
      schedulePeriodRender({ immediate: true });
    }
  }

  function syncMetricToggle() {
    $$("[data-metric]").forEach((btn) => {
      const on = btn.dataset.metric === state.metric;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function localISODate(d = new Date()) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function parseLocalISODate(iso) {
    const s = String(iso || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
    const y = Number(s.slice(0, 4));
    const m = Number(s.slice(5, 7));
    const d = Number(s.slice(8, 10));
    const dt = new Date(y, m - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null;
    return dt;
  }

  function addDaysISO(iso, delta) {
    const dt = parseLocalISODate(iso);
    if (!dt) return "";
    dt.setDate(dt.getDate() + Number(delta || 0));
    return localISODate(dt);
  }

  function daysBetweenISO(from, to) {
    const a = parseLocalISODate(from);
    const b = parseLocalISODate(to);
    if (!a || !b) return null;
    return Math.round((b - a) / 86400000);
  }

  function normalizeISODate(value) {
    const s = String(value || "").trim().slice(0, 10);
    return /^\d{4}-\d{2}-\d{2}$/.test(s) && parseLocalISODate(s) ? s : "";
  }

  function historyDateBounds() {
    const idx = ensurePeriodIndex();
    if (idx.minDate && idx.maxDate) return { from: idx.minDate, to: idx.maxDate };
    const fromMeta = String(state.agg?.meta?.perEpisodeHistoryFrom || "").slice(0, 10);
    const toMeta = localISODate();
    return {
      from: /^\d{4}-\d{2}-\d{2}$/.test(fromMeta) ? fromMeta : "",
      to: toMeta,
    };
  }

  function datePresetBounds(preset, today = localISODate()) {
    const key = String(preset || "all");
    if (key === "yesterday") {
      const y = addDaysISO(today, -1);
      return { from: y, to: y, preset: "yesterday" };
    }
    if (key === "7d") {
      return { from: addDaysISO(today, -6), to: today, preset: "7d" };
    }
    if (key === "30d") {
      return { from: addDaysISO(today, -29), to: today, preset: "30d" };
    }
    if (key === "1y") {
      return { from: addDaysISO(today, -364), to: today, preset: "1y" };
    }
    return { from: "", to: "", preset: "all" };
  }

  function inferDatePreset(from, to, today = localISODate()) {
    const f = normalizeISODate(from);
    const t = normalizeISODate(to);
    if (!f && !t) return "all";
    for (const key of ["yesterday", "7d", "30d", "1y"]) {
      const b = datePresetBounds(key, today);
      if (b.from === f && b.to === t) return key;
    }
    return "custom";
  }

  function dateRangeActive(period = state.chartPeriod) {
    return !!(normalizeISODate(period?.from) || normalizeISODate(period?.to));
  }

  function effectiveDateRange(period = state.chartPeriod) {
    const bounds = historyDateBounds();
    const from = normalizeISODate(period?.from) || bounds.from || "";
    const to = normalizeISODate(period?.to) || bounds.to || localISODate();
    if (from && to && from > to) return { from: to, to: from };
    return { from, to };
  }

  function enumerateDayKeysInclusive(from, to) {
    const start = normalizeISODate(from);
    const end = normalizeISODate(to);
    if (!start || !end || start > end) return [];
    const keys = [];
    let cur = start;
    // Cap runaway ranges (multi-year day axes) — callers should prefer month grain.
    for (let i = 0; i < 800; i++) {
      keys.push(cur);
      if (cur === end) break;
      cur = addDaysISO(cur, 1);
      if (!cur) break;
    }
    return keys;
  }

  function chartPeriodActive() {
    const { country, podcast, theme, status, q } = state.chartPeriod;
    return !!(
      dateRangeActive() ||
      country ||
      podcast ||
      theme ||
      status ||
      String(q || "").trim()
    );
  }

  function chartPeriodKey() {
    const { from, to, country, podcast, theme, status, q } = state.chartPeriod;
    return [
      normalizeISODate(from) || "all",
      normalizeISODate(to) || "all",
      country || "all",
      podcast || "all",
      theme || "all",
      status || "all",
      String(q || "").trim().toLowerCase() || "all",
    ].join("|");
  }

  function chartPeriodLabel(opts = {}) {
    const { from, to, preset, country, podcast, theme, status, q } = state.chartPeriod;
    const bits = [];
    const f = normalizeISODate(from);
    const t = normalizeISODate(to);
    if (preset === "yesterday" || (f && t && f === t && f === addDaysISO(localISODate(), -1))) {
      bits.push("Yesterday");
    } else if (preset === "7d") {
      bits.push("Last 7 days");
    } else if (preset === "30d") {
      bits.push("Last 30 days");
    } else if (preset === "1y") {
      bits.push("Last year");
    } else if (f || t) {
      if (f && t && f === t) bits.push(formatDateKey(f));
      else if (f && t) bits.push(`${formatDateKey(f)} – ${formatDateKey(t)}`);
      else if (f) bits.push(`From ${formatDateKey(f)}`);
      else bits.push(`Through ${formatDateKey(t)}`);
    }
    if (country) bits.push(country);
    if (podcast) bits.push(podcast);
    if (theme && !opts.omitTheme) bits.push(state.themeById[theme]?.name || theme);
    if (status) bits.push(status);
    const qq = String(q || "").trim();
    if (qq) bits.push(`search “${qq}”`);
    return bits.length ? bits.join(" · ") : "All time";
  }

  function ensureSearchIndex() {
    if (state._epHay) return state._epHay;
    const eps = state.episodes || [];
    const n = eps.length;
    const hays = new Array(n);
    const countries = state._epCountry;
    for (let i = 0; i < n; i++) {
      const e = eps[i];
      const epCountry = countries ? countries[i] : countryForEpisode(e);
      const th = themeIdsForIndex(i);
      const themeNames = th.map((id) => state.themeById[id]?.name || id).join(" ");
      const note = noteTextForIndex(i);
      hays[i] =
        `${e.e || ""} ${e.p || ""} ${e.a || ""} ${e.f || ""} ${epCountry} ${themeNames} ${note}`.toLowerCase();
    }
    state._epHay = hays;
    return hays;
  }

  function episodeSearchHaystack(e, i = null) {
    if (i != null) {
      const hays = ensureSearchIndex();
      return hays[i];
    }
    const epCountry = countryForEpisode(e);
    return `${e.e || ""} ${e.p || ""} ${e.a || ""} ${e.f || ""} ${epCountry}`.toLowerCase();
  }

  function episodeHasTheme(i, themeId) {
    if (i == null || !themeId) return false;
    const has = state._epThemeHas;
    if (has && has[i]) return has[i][themeId] === 1;
    return themeIdsForIndex(i).includes(themeId);
  }

  function episodeMatchesChartPeriod(e, i = null, overrides = null) {
    const base = state.chartPeriod;
    const pick = (key) =>
      overrides && Object.prototype.hasOwnProperty.call(overrides, key)
        ? overrides[key]
        : base[key];
    const from = normalizeISODate(pick("from"));
    const to = normalizeISODate(pick("to"));
    const country = pick("country");
    const podcast = pick("podcast");
    const theme = pick("theme");
    const status = pick("status");
    const q = pick("q");
    const qq = String(q || "").trim().toLowerCase();
    if (!from && !to && !country && !podcast && !theme && !status && !qq) return true;
    const d = String(e.d || "").slice(0, 10);
    if (from && d && d < from) return false;
    if (to && d && d > to) return false;
    if ((from || to) && !d) return false;
    if (country) {
      const c =
        i != null && state._epCountry ? state._epCountry[i] : countryForEpisode(e);
      if (c !== country) return false;
    }
    if (podcast && (e.p || "") !== podcast) return false;
    if (status && (e.st || "") !== status) return false;
    if (theme) {
      if (i == null) return false;
      if (!episodeHasTheme(i, theme)) return false;
    }
    if (qq) {
      if (i == null) {
        if (!episodeSearchHaystack(e, i).includes(qq)) return false;
      } else if (!ensureSearchIndex()[i].includes(qq)) {
        return false;
      }
    }
    return true;
  }

  function episodeHours(e, i = null) {
    if (i != null && state._epHours) return state._epHours[i] || 0;
    return parseDurHours(e?.dur);
  }

  function prepareEpisodeIndex() {
    const eps = state.episodes || [];
    const n = eps.length;
    const hours = new Float64Array(n);
    const countries = new Array(n);
    const hourOfDay = new Int8Array(n);
    const weekday = new Int8Array(n);
    const themeHas = new Array(n);
    hourOfDay.fill(-1);
    weekday.fill(-1);

    for (let i = 0; i < n; i++) {
      const e = eps[i];
      hours[i] = parseDurHours(e.dur);
      countries[i] = countryForEpisode(e);
      const th = themeIdsForIndex(i);
      if (th.length) {
        const map = Object.create(null);
        for (const tid of th) map[tid] = 1;
        themeHas[i] = map;
      } else {
        themeHas[i] = null;
      }
      const d = parseListenUtc(e.t);
      if (d) {
        const loc = sydneyHourAndWeekday(d);
        if (loc.hour != null) hourOfDay[i] = loc.hour;
        if (loc.weekday != null) weekday[i] = loc.weekday;
      }
    }

    state._epHours = hours;
    state._epCountry = countries;
    state._epHay = null; // built lazily on first text search
    state._epHour = hourOfDay;
    state._epWeekday = weekday;
    state._epThemeHas = themeHas;
    state._matchedCache = null;
    state._matchedCacheKey = "";
    state._countryOptionsHtml = "";
    state._podcastOptionsHtml = "";
    state._notesCoverage = null;
  }

  function invalidateMatchedCache() {
    state._matchedCache = null;
    state._matchedCacheKey = "";
  }

  function matchedEpisodeIndexes(overrides = null) {
    const key = overrides
      ? `${chartPeriodKey()}|ov:${JSON.stringify(overrides)}`
      : chartPeriodKey();
    if (state._matchedCache && state._matchedCacheKey === key) return state._matchedCache;
    const eps = state.episodes || [];
    const out = [];
    for (let i = 0; i < eps.length; i++) {
      if (episodeMatchesChartPeriod(eps[i], i, overrides)) out.push(i);
    }
    state._matchedCache = out;
    state._matchedCacheKey = key;
    return out;
  }

  function yieldToPaint() {
    return new Promise((resolve) => {
      requestAnimationFrame(() => resolve());
    });
  }

  function setFilteringUi(on) {
    document.body.classList.toggle("is-filtering", !!on);
  }

  async function runPeriodRender(gen) {
    if (gen !== state._renderGen) return;
    // Hot path first: summary + lists so the click feels answered.
    updatePeriodSummary();
    renderHeroStats();
    renderEpisodeList();
    if (gen !== state._renderGen) return;

    // Theme drill-down must paint before other charts. Otherwise the parent
    // bars stay tappable for hundreds of ms while state already moved, and a
    // second tap opens a different parent than the one on screen after paint.
    pruneInvisibleThemeSelection();
    renderThemeChart();
    renderThemeDetail(state.activeTheme || state.focusedParentId || "");
    renderThemeMatchPanel();
    renderThemeYearChart();
    syncThemeSelectOptions();
    if (gen !== state._renderGen) return;
    await yieldToPaint();
    if (gen !== state._renderGen) return;

    renderTrendChart();
    renderCumulativeChart();
    renderYearChart();
    if (gen !== state._renderGen) return;
    await yieldToPaint();
    if (gen !== state._renderGen) return;

    renderYoYChart();
    renderTopPodcastsChart();
    if (gen !== state._renderGen) return;
    await yieldToPaint();
    if (gen !== state._renderGen) return;

    renderWeekdayHourCharts();
    renderFolderStatusCharts();
    renderCountryChart();
    renderDurationChart();
    renderHeatmap();
    if (gen === state._renderGen) setFilteringUi(false);
  }

  function schedulePeriodRender({ immediate = false } = {}) {
    const gen = ++state._renderGen;
    if (state._renderTimer) {
      clearTimeout(state._renderTimer);
      state._renderTimer = 0;
    }
    setFilteringUi(true);
    const kick = () => {
      state._renderTimer = 0;
      runPeriodRender(gen);
    };
    if (immediate) {
      queueMicrotask(kick);
    } else {
      // Let the browser paint the updated <select> / badge before heavy work.
      state._renderTimer = setTimeout(kick, 0);
    }
  }

  function patchChartPeriod(patch, opts) {
    applyChartPeriod({ ...state.chartPeriod, ...patch }, opts);
  }

  function syncThemeUiFromPeriod() {
    const themeId = state.chartPeriod.theme || "";
    state.activeTheme = themeId;
    state.focusedParentId = themeId;
  }

  function ensurePeriodIndex() {
    if (state._periodIndex) return state._periodIndex;
    const years = new Set();
    let minDate = "";
    let maxDate = "";
    for (const e of state.episodes || []) {
      const d = String(e.d || "").slice(0, 10);
      const y = e.y != null && e.y !== "" ? String(e.y) : d.slice(0, 4);
      if (y && y.length === 4) years.add(y);
      if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
        if (!minDate || d < minDate) minDate = d;
        if (!maxDate || d > maxDate) maxDate = d;
      }
    }
    state._periodIndex = {
      years: [...years].sort((a, b) => Number(b) - Number(a)),
      minDate,
      maxDate,
    };
    return state._periodIndex;
  }

  function invalidateChartStats() {
    state._chartStats = null;
    state._chartStatsKey = "";
    state._chartStatsCache = null;
    state._localStats = null;
    invalidateMatchedCache();
  }

  function applyChartPeriod(next, { rerender = true } = {}) {
    const pick = (key) =>
      Object.prototype.hasOwnProperty.call(next, key)
        ? String(next[key] || "")
        : String(state.chartPeriod[key] || "");
    let from = normalizeISODate(
      Object.prototype.hasOwnProperty.call(next, "from") ? next.from : state.chartPeriod.from
    );
    let to = normalizeISODate(
      Object.prototype.hasOwnProperty.call(next, "to") ? next.to : state.chartPeriod.to
    );
    if (from && to && from > to) {
      const swap = from;
      from = to;
      to = swap;
    }
    let preset = Object.prototype.hasOwnProperty.call(next, "preset")
      ? String(next.preset || "")
      : String(state.chartPeriod.preset || "");
    if (!preset || preset === "custom") {
      preset = inferDatePreset(from, to);
    } else if (preset !== "all" && preset !== "custom") {
      // Keep an explicit preset only if bounds still match it.
      const expected = datePresetBounds(preset);
      if (expected.from !== from || expected.to !== to) preset = inferDatePreset(from, to);
    } else if (!from && !to) {
      preset = "all";
    }
    const country = pick("country");
    const podcast = pick("podcast");
    const theme = pick("theme");
    const status = pick("status");
    const q = Object.prototype.hasOwnProperty.call(next, "q")
      ? String(next.q || "")
      : String(state.chartPeriod.q || "");
    state.chartPeriod = { from, to, preset, country, podcast, theme, status, q };
    syncThemeUiFromPeriod();
    invalidateChartStats();
    syncPeriodControls({ skipThemes: true });
    updateMetricLabels();
    syncFilterBadge();
    const summary = $("#periodSummary");
    if (summary) {
      const label = chartPeriodLabel();
      summary.innerHTML = chartPeriodActive()
        ? `<strong>${escapeHtml(label)}</strong> — updating…`
        : `<strong>All time</strong> — charts use the full history.`;
    }
    if (!rerender || !state.agg) return;
    state.page = 0;
    state.barReveal.top = BAR_PAGE;
    state.barReveal.country = BAR_PAGE;
    state.barReveal.theme = BAR_PAGE;
    schedulePeriodRender();
  }

  function availableCountries() {
    if (state._epCountry) {
      const counts = Object.create(null);
      for (let i = 0; i < state._epCountry.length; i++) {
        const c = state._epCountry[i];
        counts[c] = (counts[c] || 0) + 1;
      }
      return Object.keys(counts)
        .sort((a, b) => {
          if (a === "Unknown") return 1;
          if (b === "Unknown") return -1;
          return counts[b] - counts[a] || a.localeCompare(b);
        })
        .map((c) => ({ name: c, count: counts[c] }));
    }
    const counts = Object.create(null);
    for (const e of state.episodes || []) {
      const c = countryForEpisode(e);
      counts[c] = (counts[c] || 0) + 1;
    }
    return Object.keys(counts)
      .sort((a, b) => {
        if (a === "Unknown") return 1;
        if (b === "Unknown") return -1;
        return counts[b] - counts[a] || a.localeCompare(b);
      })
      .map((c) => ({ name: c, count: counts[c] }));
  }

  function ensureCountryOptionsHtml() {
    if (state._countryOptionsHtml) return state._countryOptionsHtml;
    const countries = availableCountries();
    state._countryOptionsHtml =
      `<option value="">All countries</option>` +
      countries
        .map(
          (c) =>
            `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)} (${fmt(c.count)})</option>`
        )
        .join("");
    return state._countryOptionsHtml;
  }

  function ensurePodcastOptionsHtml() {
    if (state._podcastOptionsHtml) return state._podcastOptionsHtml;
    if (!state.podcasts) return `<option value="">All shows</option>`;
    const isUuidTitle = (name) =>
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(name || ""));
    const names = state.podcasts
      .slice()
      .sort((a, b) => {
        const an = String(a.p || "");
        const bn = String(b.p || "");
        const aUuid = isUuidTitle(an);
        const bUuid = isUuidTitle(bn);
        // Keep anonymous UUID titles after named shows so A–Z is usable.
        if (aUuid !== bUuid) return aUuid ? 1 : -1;
        return an.localeCompare(bn, undefined, { sensitivity: "base" });
      })
      .map((p) => p.p)
      .filter(Boolean);
    state._podcastOptionsHtml =
      `<option value="">All shows</option>` +
      names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("");
    return state._podcastOptionsHtml;
  }

  function syncThemeSelectOptions() {
    const themeSel = $("#periodTheme");
    if (!themeSel || !state.themesDoc?.themes) return;
    const selected = state.chartPeriod.theme || "";
    const themes = themesPresentInFilter(flatThemes()).slice();
    // Keep a selected theme visible even if the current filter set hides it.
    if (selected && !themes.some((t) => t.id === selected)) {
      const t = state.themeById[selected];
      if (t) themes.push(t);
    }
    themes.sort((a, b) =>
      String(a.name || "").localeCompare(String(b.name || ""), undefined, {
        sensitivity: "base",
      })
    );
    const opts = ['<option value="">All themes</option>'];
    for (const t of themes) {
      opts.push(`<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`);
    }
    themeSel.innerHTML = opts.join("");
    themeSel.value = selected;
    // Drop a theme facet that no longer intersects the other filters.
    if (selected && themeSel.value !== selected) {
      state.chartPeriod.theme = "";
      syncThemeUiFromPeriod();
      themeSel.value = "";
      invalidateChartStats();
      schedulePeriodRender();
    }
  }

  function syncDatePresetButtons() {
    const active = state.chartPeriod.preset || inferDatePreset(state.chartPeriod.from, state.chartPeriod.to);
    $$("[data-date-preset]").forEach((btn) => {
      const on = btn.getAttribute("data-date-preset") === active;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function syncPeriodControls({ skipThemes = false } = {}) {
    const fromInput = $("#periodFrom");
    const toInput = $("#periodTo");
    const countrySel = $("#periodCountry");
    const podcastSel = $("#periodPodcast");
    const statusSel = $("#periodStatus");
    const qInput = $("#periodQ");
    if (!fromInput || !toInput) return;
    const { from, to, country, podcast, status, q } = state.chartPeriod;
    const bounds = historyDateBounds();
    const min = bounds.from || "";
    const max = bounds.to || localISODate();
    if (min) {
      fromInput.min = min;
      toInput.min = min;
    } else {
      fromInput.removeAttribute("min");
      toInput.removeAttribute("min");
    }
    if (max) {
      fromInput.max = max;
      toInput.max = max;
    } else {
      fromInput.removeAttribute("max");
      toInput.removeAttribute("max");
    }
    fromInput.value = normalizeISODate(from) || "";
    toInput.value = normalizeISODate(to) || "";
    syncDatePresetButtons();

    if (countrySel && state.episodes) {
      if (!countrySel.options.length || countrySel.dataset.built !== "1") {
        countrySel.innerHTML = ensureCountryOptionsHtml();
        countrySel.dataset.built = "1";
      }
      countrySel.value = country || "";
    }

    if (podcastSel && state.podcasts) {
      if (!podcastSel.options.length || podcastSel.dataset.built !== "1") {
        podcastSel.innerHTML = ensurePodcastOptionsHtml();
        podcastSel.dataset.built = "1";
      }
      podcastSel.value = podcast || "";
    }

    if (!skipThemes) syncThemeSelectOptions();

    if (statusSel) statusSel.value = status || "";
    if (qInput && qInput.value !== (q || "")) qInput.value = q || "";
    refreshSearchableSelects();
    requestAnimationFrame(() => layoutDesktopFilterOverflow());
  }

  function refreshSearchableSelects() {
    ["periodPodcast", "periodCountry", "periodTheme"].forEach((id) => {
      const el = document.getElementById(id);
      el?._comboPaint?.();
    });
  }

  function isCompactFilterUi() {
    return window.matchMedia("(max-width: 860px)").matches;
  }

  function syncVisualViewportVars() {
    const vv = window.visualViewport;
    const top = vv ? vv.offsetTop : 0;
    const left = vv ? vv.offsetLeft : 0;
    const width = vv ? vv.width : window.innerWidth;
    const height = vv ? vv.height : window.innerHeight;
    const root = document.documentElement.style;
    root.setProperty("--vv-top", `${Math.round(top)}px`);
    root.setProperty("--vv-left", `${Math.round(left)}px`);
    root.setProperty("--vv-width", `${Math.round(width)}px`);
    root.setProperty("--vv-height", `${Math.round(height)}px`);
  }

  /** Last-resort lock: if anything expands the page sideways, pin scroll and clip. */
  function guardHorizontalOverflow() {
    const root = document.documentElement;
    const spill = root.scrollWidth - window.innerWidth;
    if (spill > 1) {
      root.classList.add("edge-lock");
      if (window.scrollX || root.scrollLeft) {
        window.scrollTo(0, window.scrollY || window.pageYOffset || 0);
      }
    } else {
      root.classList.remove("edge-lock");
    }
  }

  let comboPickerState = null;

  function ensureComboPickerHost() {
    let host = $("#comboPickerHost");
    if (host) return host;
    host = document.createElement("div");
    host.id = "comboPickerHost";
    host.className = "combo-picker-host";
    host.hidden = true;
    host.innerHTML = `
      <div class="combo-picker" role="dialog" aria-modal="true" aria-labelledby="comboPickerTitle">
        <div class="combo-picker-chrome">
          <button type="button" class="sheet-text-btn" data-combo-cancel>Cancel</button>
          <h2 id="comboPickerTitle" class="combo-picker-title">Choose</h2>
          <button type="button" class="sheet-text-btn sheet-done" data-combo-done>Done</button>
        </div>
        <div class="combo-picker-search">
          <input type="search" class="combo-picker-input" id="comboPickerInput" autocomplete="off" spellcheck="false" />
        </div>
        <ul class="combo-picker-list" id="comboPickerList" role="listbox"></ul>
      </div>`;
    document.body.appendChild(host);
    host.querySelector("[data-combo-cancel]")?.addEventListener("click", () => closeComboPicker(false));
    host.querySelector("[data-combo-done]")?.addEventListener("click", () => closeComboPicker(false));
    host.addEventListener("click", (e) => {
      if (e.target === host) closeComboPicker(false);
    });
    $("#comboPickerInput")?.addEventListener("input", () => {
      if (comboPickerState) renderComboPickerList(comboPickerState.queryFromInput());
    });
    $("#comboPickerList")?.addEventListener("click", (e) => {
      const li = e.target.closest("[data-value]");
      if (!li || !comboPickerState) return;
      comboPickerState.pick(li.getAttribute("data-value"));
    });
    $("#comboPickerInput")?.addEventListener("keydown", (e) => {
      if (!comboPickerState) return;
      if (e.key === "Escape") {
        e.preventDefault();
        closeComboPicker(false);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const first = $("#comboPickerList .combo-option");
        if (first) comboPickerState.pick(first.getAttribute("data-value"));
      }
    });
    return host;
  }

  function renderComboPickerList(query) {
    if (!comboPickerState) return;
    const { select, emptyLabel } = comboPickerState;
    const list = $("#comboPickerList");
    if (!list) return;
    const matches = filterSelectOptions(select, query);
    comboPickerState.filtered = matches;
    list.innerHTML = matches.length
      ? matches
          .map((o) => {
            const selected = o.value === select.value;
            const label = o.value ? o.textContent : emptyLabel;
            return `<li role="option" class="combo-option${selected ? " is-selected" : ""}" data-value="${escapeHtml(
              o.value
            )}" aria-selected="${selected ? "true" : "false"}">${escapeHtml(label)}</li>`;
          })
          .join("")
      : `<li class="combo-empty">No matches</li>`;
    const selectedEl = list.querySelector(".combo-option.is-selected");
    if (selectedEl) selectedEl.scrollIntoView({ block: "nearest" });
  }

  function resetViewportAfterOverlay() {
    syncVisualViewportVars();
    try {
      const y = window.scrollY || window.pageYOffset || 0;
      window.scrollTo(0, y);
      document.documentElement.scrollLeft = 0;
      document.body.scrollLeft = 0;
    } catch (_) {}
    guardHorizontalOverflow();
    // Second pass after iOS finishes keyboard / zoom teardown.
    requestAnimationFrame(() => {
      syncVisualViewportVars();
      guardHorizontalOverflow();
      setTimeout(() => {
        syncVisualViewportVars();
        guardHorizontalOverflow();
      }, 120);
    });
  }

  function closeComboPicker(restoreFocus) {
    const host = $("#comboPickerHost");
    if (!host || host.hidden) {
      comboPickerState = null;
      document.body.classList.remove("combo-picker-open");
      resetViewportAfterOverlay();
      return;
    }
    const originInput = comboPickerState?.originInput;
    host.hidden = true;
    document.body.classList.remove("combo-picker-open");
    comboPickerState = null;
    if (restoreFocus && originInput) {
      requestAnimationFrame(() => originInput.focus({ preventScroll: true }));
    } else {
      originInput?.blur();
    }
    resetViewportAfterOverlay();
  }

  function openComboPicker(select, { emptyLabel, title, originInput }) {
    syncVisualViewportVars();
    const host = ensureComboPickerHost();
    const pickerInput = $("#comboPickerInput");
    const titleEl = $("#comboPickerTitle");
    if (titleEl) titleEl.textContent = title || emptyLabel || "Choose";
    if (pickerInput) {
      pickerInput.value = "";
      pickerInput.placeholder = `Search ${String(emptyLabel || "options")
        .replace(/^All\s+/i, "")
        .toLowerCase()}…`;
    }
    comboPickerState = {
      select,
      emptyLabel,
      originInput,
      filtered: [],
      queryFromInput: () => pickerInput?.value || "",
      pick: (value) => {
        const next = String(value ?? "");
        if (select.value !== next) {
          select.value = next;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        select._comboPaint?.();
        closeComboPicker(false);
      },
    };
    renderComboPickerList("");
    host.hidden = false;
    document.body.classList.add("combo-picker-open");
    requestAnimationFrame(() => {
      pickerInput?.focus({ preventScroll: true });
    });
  }

  function filterSelectOptions(select, query) {
    const q = String(query || "").trim().toLowerCase();
    const opts = [...select.options];
    if (!q) return opts;
    // While searching, only show real matches — keep "All …" for the empty query.
    return opts.filter((o) => o.value && o.textContent.toLowerCase().includes(q));
  }

  function upgradeSearchableSelect(select, { emptyLabel = "All", title = "" } = {}) {
    if (!select || select.dataset.combo === "1") return;
    select.dataset.combo = "1";
    const wrap = document.createElement("div");
    wrap.className = "combo";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("combo-native");
    select.tabIndex = -1;

    const pickerTitle =
      title ||
      (select.getAttribute("aria-label") || emptyLabel).replace(/^Filter by\s+/i, "");

    const input = document.createElement("input");
    input.type = "search";
    input.className = "combo-input";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.autocomplete = "off";
    input.spellcheck = false;
    input.readOnly = false;
    const listId = `${select.id}-list`;
    input.id = `${select.id}Input`;
    input.setAttribute("aria-controls", listId);
    input.setAttribute(
      "aria-label",
      select.getAttribute("aria-label") || emptyLabel
    );

    const list = document.createElement("ul");
    list.id = listId;
    list.className = "combo-list";
    list.hidden = true;
    list.setAttribute("role", "listbox");

    wrap.appendChild(input);
    wrap.appendChild(list);

    let highlight = -1;
    let filtered = [];
    let desktopOpen = false;
    let repositionBound = null;

    const selectedLabel = () => {
      const opt = select.options[select.selectedIndex];
      return opt ? opt.textContent : emptyLabel;
    };

    const paintClosed = () => {
      input.value = select.value ? selectedLabel() : "";
      input.placeholder = emptyLabel;
      highlight = -1;
    };

    /**
     * Desktop lists must leave the sticky filter chrome. Parents use
     * overflow-x:hidden for edge containment, which also clips absolute
     * dropdowns — so portal to <body> and pin with position:fixed.
     */
    const positionDesktopList = () => {
      if (!desktopOpen || list.hidden) return;
      const r = input.getBoundingClientRect();
      const gutter = 8;
      const width = Math.max(160, Math.round(r.width));
      let left = Math.round(r.left);
      left = Math.min(left, window.innerWidth - width - gutter);
      left = Math.max(gutter, left);
      const spaceBelow = window.innerHeight - r.bottom - gutter;
      const spaceAbove = r.top - gutter;
      const preferBelow = spaceBelow >= 160 || spaceBelow >= spaceAbove;
      const maxH = Math.min(280, Math.max(120, preferBelow ? spaceBelow : spaceAbove));
      const top = preferBelow
        ? Math.round(r.bottom + 4)
        : Math.round(Math.max(gutter, r.top - 4 - maxH));
      list.style.position = "fixed";
      list.style.left = `${left}px`;
      list.style.top = `${top}px`;
      list.style.width = `${width}px`;
      list.style.right = "auto";
      list.style.maxHeight = `${Math.round(maxH)}px`;
      list.style.zIndex = "240";
    };

    const detachDesktopListeners = () => {
      if (!repositionBound) return;
      window.removeEventListener("resize", repositionBound);
      window.removeEventListener("scroll", repositionBound, true);
      window.visualViewport?.removeEventListener("resize", repositionBound);
      window.visualViewport?.removeEventListener("scroll", repositionBound);
      repositionBound = null;
    };

    const closeDesktop = () => {
      desktopOpen = false;
      detachDesktopListeners();
      list.hidden = true;
      list.classList.remove("is-ported");
      input.setAttribute("aria-expanded", "false");
      highlight = -1;
      // Park the list back under the combo so DOM order stays predictable.
      if (list.parentElement !== wrap) wrap.appendChild(list);
      list.removeAttribute("style");
      paintClosed();
    };

    const syncHighlight = () => {
      $$(".combo-option", list).forEach((li, i) => {
        li.classList.toggle("is-active", i === highlight);
      });
      const active = list.querySelector(".combo-option.is-active");
      active?.scrollIntoView({ block: "nearest" });
    };

    const renderDesktopList = (query) => {
      filtered = filterSelectOptions(select, query);
      highlight = filtered.length ? 0 : -1;
      list.innerHTML = filtered.length
        ? filtered
            .map((o, i) => {
              const selected = o.value === select.value;
              const label = o.value ? o.textContent : emptyLabel;
              return `<li role="option" class="combo-option${selected ? " is-selected" : ""}${
                i === highlight ? " is-active" : ""
              }" data-value="${escapeHtml(o.value)}" data-i="${i}" aria-selected="${
                selected ? "true" : "false"
              }">${escapeHtml(label)}</li>`;
            })
            .join("")
        : `<li class="combo-empty">No matches</li>`;
      if (list.parentElement !== document.body) {
        document.body.appendChild(list);
      }
      list.classList.add("is-ported");
      list.hidden = false;
      desktopOpen = true;
      input.setAttribute("aria-expanded", "true");
      positionDesktopList();
      if (!repositionBound) {
        repositionBound = () => positionDesktopList();
        window.addEventListener("resize", repositionBound);
        window.addEventListener("scroll", repositionBound, true);
        window.visualViewport?.addEventListener("resize", repositionBound);
        window.visualViewport?.addEventListener("scroll", repositionBound);
      }
    };

    const pickDesktop = (value) => {
      const next = String(value ?? "");
      if (select.value !== next) {
        select.value = next;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        paintClosed();
      }
      closeDesktop();
      input.blur();
    };

    const openMobile = () => {
      closeDesktop();
      input.setAttribute("aria-expanded", "true");
      openComboPicker(select, {
        emptyLabel,
        title: pickerTitle,
        originInput: input,
      });
    };

    input.addEventListener("pointerdown", (e) => {
      if (!isCompactFilterUi()) return;
      // Open the full-screen picker instead of the clipped inline list.
      e.preventDefault();
      openMobile();
    });
    input.addEventListener("focus", () => {
      if (isCompactFilterUi()) {
        // Keyboard focus (e.g. VoiceOver) — still use the mobile picker.
        if (!document.body.classList.contains("combo-picker-open")) openMobile();
        return;
      }
      input.value = "";
      renderDesktopList("");
    });
    input.addEventListener("input", () => {
      if (isCompactFilterUi()) return;
      renderDesktopList(input.value);
    });
    input.addEventListener("keydown", (e) => {
      if (isCompactFilterUi()) {
        if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
          e.preventDefault();
          openMobile();
        }
        return;
      }
      if (list.hidden && (e.key === "ArrowDown" || e.key === "Enter")) {
        renderDesktopList(input.value);
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!filtered.length) return;
        highlight = (highlight + 1) % filtered.length;
        syncHighlight();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (!filtered.length) return;
        highlight = (highlight - 1 + filtered.length) % filtered.length;
        syncHighlight();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (highlight >= 0 && filtered[highlight]) pickDesktop(filtered[highlight].value);
        else if (filtered[0]) pickDesktop(filtered[0].value);
      } else if (e.key === "Escape") {
        e.preventDefault();
        closeDesktop();
        input.blur();
      }
    });
    list.addEventListener("mousedown", (e) => {
      const li = e.target.closest("[data-value]");
      if (!li) return;
      e.preventDefault();
      pickDesktop(li.getAttribute("data-value"));
    });
    input.addEventListener("blur", () => {
      if (isCompactFilterUi()) return;
      window.setTimeout(() => {
        const active = document.activeElement;
        if (wrap.contains(active) || list.contains(active)) return;
        closeDesktop();
      }, 140);
    });

    select._comboPaint = paintClosed;
    select._comboInput = input;
    select._comboOpenMobile = openMobile;
    select._comboCloseDesktop = closeDesktop;
    paintClosed();
  }

  function activeFacetCount({ includePodcast = true } = {}) {
    const p = state.chartPeriod;
    let n = 0;
    if (dateRangeActive(p)) n += 1;
    if (p.country) n += 1;
    if (includePodcast && p.podcast) n += 1;
    if (p.theme) n += 1;
    if (p.status) n += 1;
    if (String(p.q || "").trim()) n += 1;
    return n;
  }

  function syncFilterBadge() {
    const badge = $("#filterBadge");
    const toggle = $("#filterSheetToggle");
    const clearBtn = $("#periodClear");
    // Show lives on its own control; badge counts the Filters sheet facets.
    const n = activeFacetCount({ includePodcast: false });
    const any =
      activeFacetCount({ includePodcast: true }) > 0 ||
      !!String(state.chartPeriod.q || "").trim();
    if (badge) {
      if (n > 0) {
        badge.hidden = false;
        badge.textContent = String(n);
      } else {
        badge.hidden = true;
      }
    }
    toggle?.classList.toggle("has-filters", n > 0);
    if (clearBtn) clearBtn.hidden = !any;
  }

  function clearFilterOverflowHidden() {
    $$("#periodControls .period-field").forEach((el) => {
      el.classList.remove("is-overflow-hidden");
    });
    $("#periodControls")?.classList.remove("is-measuring");
  }

  function placeFilterToggle() {
    const toggle = $("#filterSheetToggle");
    const toolbar = $("#periodToolbar");
    const line = $("#periodFilterLine");
    const clearBtn = $("#periodClear");
    if (!toggle) return;
    if (isCompactFilterUi()) {
      if (!toolbar) return;
      if (clearBtn && clearBtn.parentElement === toolbar) {
        toolbar.insertBefore(toggle, clearBtn);
      } else if (toggle.parentElement !== toolbar) {
        toolbar.appendChild(toggle);
      }
      return;
    }
    // Desktop: Filters stays at the end of the facet row.
    if (line && toggle.parentElement !== line) line.appendChild(toggle);
  }

  function layoutDesktopFilterOverflow() {
    const controls = $("#periodControls");
    const line = $("#periodFilterLine");
    const toggle = $("#filterSheetToggle");
    if (!controls || !toggle) return;
    if (isCompactFilterUi()) {
      clearFilterOverflowHidden();
      return;
    }
    placeFilterToggle();
    // Expanded: keep every facet visible in the same bar (wrapped).
    if (document.body.classList.contains("filters-expanded")) {
      clearFilterOverflowHidden();
      toggle.hidden = false;
      toggle.title = "Hide extra filters";
      toggle.classList.add("has-overflow");
      return;
    }
    const fields = $$(":scope > .period-field", controls);
    clearFilterOverflowHidden();
    // Measure natural widths on one line, then hide what does not fit.
    controls.classList.add("is-measuring");
    const gap = 10;
    const avail = Math.max(0, controls.getBoundingClientRect().width);
    let used = 0;
    let hidden = 0;
    for (const field of fields) {
      const w = field.getBoundingClientRect().width;
      const next = used === 0 ? w : used + gap + w;
      if (next > avail + 0.5 && used > 0) {
        field.classList.add("is-overflow-hidden");
        hidden += 1;
      } else {
        used = next;
      }
    }
    controls.classList.remove("is-measuring");
    toggle.hidden = false;
    toggle.title = hidden > 0 ? `More filters (${hidden})` : "More filters";
    toggle.classList.toggle("has-overflow", hidden > 0);
    if (line) line.dataset.overflowCount = String(hidden);
  }

  function placeFilterPanel(inSheet) {
    const panel = $("#filterPanel");
    const sheetBody = $("#filterSheetBody");
    const secondary = $("#periodSecondary");
    const line = $("#periodFilterLine");
    const toggle = $("#filterSheetToggle");
    if (!panel || !sheetBody || !secondary) return;
    // Desktop never uses the bottom sheet — facets stay in the glass bar.
    if (!isCompactFilterUi()) {
      if (panel.parentElement !== secondary) secondary.appendChild(panel);
      if (toggle && line) line.appendChild(toggle);
      return;
    }
    if (inSheet) {
      clearFilterOverflowHidden();
      if (toggle && secondary) secondary.appendChild(toggle);
      if (panel.parentElement !== sheetBody) sheetBody.appendChild(panel);
    } else {
      if (panel.parentElement !== secondary) secondary.appendChild(panel);
      placeFilterToggle();
    }
  }

  function setDesktopFiltersExpanded(open) {
    const on = !!open;
    closeComboPicker(false);
    document.body.classList.toggle("filters-expanded", on);
    document.body.classList.remove("filter-sheet-open");
    const toggle = $("#filterSheetToggle");
    const backdrop = $("#filterSheetBackdrop");
    const sheet = $("#filterSheetPanel");
    if (toggle) toggle.setAttribute("aria-expanded", on ? "true" : "false");
    if (backdrop) backdrop.hidden = true;
    if (sheet) sheet.hidden = true;
    placeFilterPanel(false);
    placeFilterToggle();
    if (on) {
      clearFilterOverflowHidden();
      requestAnimationFrame(() => {
        ($("#periodStatus") || $("#periodTheme") || $("#periodQ"))?.focus?.({
          preventScroll: true,
        });
      });
    }
    layoutDesktopFilterOverflow();
  }

  function setFilterSheetOpen(open) {
    // Desktop: expand overflow facets in the same filter bar (no foreign sheet).
    if (!isCompactFilterUi()) {
      setDesktopFiltersExpanded(open);
      return;
    }
    const on = !!open;
    if (!on) closeComboPicker(false);
    document.body.classList.remove("filters-expanded");
    document.body.classList.toggle("filter-sheet-open", on);
    const toggle = $("#filterSheetToggle");
    const backdrop = $("#filterSheetBackdrop");
    const sheet = $("#filterSheetPanel");
    if (toggle) toggle.setAttribute("aria-expanded", on ? "true" : "false");
    if (backdrop) backdrop.hidden = !on;
    if (sheet) sheet.hidden = !on;
    placeFilterPanel(on);
    placeFilterToggle();
    if (on) {
      requestAnimationFrame(() => {
        ($("#periodQ") || $("#periodFrom"))?.focus?.({ preventScroll: true });
      });
    } else {
      resetViewportAfterOverlay();
      requestAnimationFrame(() => layoutDesktopFilterOverflow());
    }
  }

  function updatePeriodSummary() {
    const el = $("#periodSummary");
    syncFilterBadge();
    if (!el) return;
    const label = chartPeriodLabel();
    if (!chartPeriodActive()) {
      el.innerHTML = `<strong>All time</strong> — charts use the full history.`;
      return;
    }
    const stats = ensureChartStats();
    const top = topPodcastItems()
      .slice()
      .sort((a, b) =>
        metricIsHours() ? b.hours - a.hours || a.name.localeCompare(b.name) : b.count - a.count || a.name.localeCompare(b.name)
      )[0];
    const topBit = top
      ? metricIsHours()
        ? ` · top show <strong>${escapeHtml(top.name)}</strong> (${fmtHours(top.hours)}h)`
        : ` · top show <strong>${escapeHtml(top.name)}</strong> (${fmt(top.count)} eps)`
      : "";
    el.innerHTML =
      `<strong>${escapeHtml(label)}</strong> — ${fmt(stats.episodeCount)} episodes · ${fmtHours(stats.hoursTotal)}h · ${fmt(stats.podcastCount)} shows` +
      topBit;
  }

  function updateMetricLabels() {
    const hours = metricIsHours();
    const period = chartPeriodLabel();
    const periodSuffix = chartPeriodActive() ? ` · ${period}` : "";
    const grain = periodAxisKeys().grain;
    const setText = (sel, episodesText, hoursText) => {
      const el = $(sel);
      if (el) el.textContent = (hours ? hoursText : episodesText) + periodSuffix;
    };
    setText(
      "#trendLead",
      grain === "day"
        ? "Daily episode volume in the selected period."
        : "Monthly episode volume with a 3-month average.",
      grain === "day"
        ? "Daily hours of episode duration in the selected period."
        : "Monthly hours of episode duration with a 3-month average."
    );
    setText("#cumChartTitle", "Cumulative episodes", "Cumulative hours");
    if (grain === "day") {
      setText("#yearChartTitle", "Episodes by day", "Hours by day");
    } else if (grain === "month" && dateRangeActive()) {
      setText("#yearChartTitle", "Episodes by month", "Hours by month");
    } else {
      setText("#yearChartTitle", "Episodes by year", "Hours by year");
    }
    setText("#yoyChartNote", "Compare January–December volume across years.", "Compare January–December listening hours across years.");
    setText("#topChartTitle", "Podcasts by listens", "Podcasts by hours");
    setText("#folderChartTitle", "Folders", "Folders by hours");
    setText("#countryChartTitle", "Countries of origin", "Countries by hours");
    setText("#weekdayChartTitle", "Day of week (AEST/AEDT)", "Day of week by hours (AEST/AEDT)");
    setText("#hourChartTitle", "Hour of day (AEST/AEDT)", "Hour of day by hours (AEST/AEDT)");
    const heat = $("#heatmapNote");
    if (heat) {
      heat.textContent = hours
        ? chartPeriodActive()
          ? "Daily hours of episode duration for the selected period. Darker = more listening time."
          : "Daily hours of episode duration for the last ~12 months. Darker = more listening time."
        : chartPeriodActive()
          ? "Daily episode count for the selected period. Darker = more listens."
          : "Daily episode count for the last ~12 months. Darker = more listens.";
    }
  }

  async function loadJSON(path) {
    const bust = path.includes("?") ? "&" : "?";
    const res = await fetch(`${path}${bust}_=${Date.now()}`, {
      cache: "reload",
    });
    if (!res.ok) throw new Error(`Could not load ${path}`);
    return res.json();
  }

  function isDark() {
    return document.documentElement.getAttribute("data-theme") === "dark";
  }

  function palette() {
    return isDark() ? COLORS_DARK : COLORS;
  }

  function categorical() {
    return isDark() ? CATEGORICAL_DARK : CATEGORICAL;
  }

  function chartChrome() {
    if (isDark()) {
      return {
        label: "rgba(255,255,255,0.92)",
        muted: "rgba(235,235,245,0.6)",
        grid: "rgba(84,84,88,0.45)",
        tooltipBg: "rgba(44,44,46,0.96)",
        doughnutBorder: "#1C1C1E",
      };
    }
    return {
      label: "rgba(0,0,0,0.88)",
      muted: "rgba(60,60,67,0.6)",
      grid: "rgba(60,60,67,0.12)",
      tooltipBg: "rgba(28,28,30,0.94)",
      doughnutBorder: "#FFFFFF",
    };
  }

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (_) {}
    syncThemeToggle();
  }

  function syncThemeToggle() {
    const btn = $("#themeToggle");
    if (!btn) return;
    const dark = isDark();
    btn.setAttribute("aria-pressed", dark ? "true" : "false");
    btn.textContent = dark ? "Light" : "Dark";
    btn.title = dark ? "Switch to light mode" : "Switch to dark mode";
  }

  function destroyChart(key) {
    const chart = state.charts[key];
    if (!chart) return;
    if (chart.$hBarClick && chart.canvas) {
      chart.canvas.removeEventListener("click", chart.$hBarClick);
      chart.canvas.removeEventListener("pointerup", chart.$hBarClick);
      chart.$hBarClick = null;
    }
    chart.destroy();
    delete state.charts[key];
  }

  /** Format the number painted at the tip of a bar (not axis ticks). */
  function formatBarEndValue(value, valueLabel) {
    if (valueLabel === "Avg minutes") {
      const n = Number(value) || 0;
      return (Math.round(n * 10) / 10).toLocaleString(undefined, {
        maximumFractionDigits: 1,
      });
    }
    return fmtMetric(value);
  }

  /**
   * Draw the metric next to every bar so readers need not scan the value axis.
   * Works for horizontal (indexAxis: "y") and vertical bars.
   */
  const barValueLabelsPlugin = {
    id: "barValueLabels",
    afterDatasetsDraw(chart) {
      // Opt out via chart.$barEndLabels === false. Formatter is stored on the
      // chart instance (not options.plugins) so Chart.js scriptable-option
      // resolution cannot call it with a context object.
      if (chart.$barEndLabels === false) return;
      const chrome = chartChrome();
      const fmtFn =
        typeof chart.$formatBarEnd === "function"
          ? chart.$formatBarEnd
          : typeof chart.canvas?.__formatBarEnd === "function"
            ? chart.canvas.__formatBarEnd
            : (v) => fmtMetric(v);
      const horizontal = chart.options.indexAxis === "y";
      const { ctx, chartArea } = chart;
      if (!chartArea) return;
      const fontSize = isCompactFilterUi() ? 11 : 12;
      ctx.save();
      ctx.font = `600 ${fontSize}px Figtree, system-ui, sans-serif`;
      ctx.textBaseline = "middle";
      for (let di = 0; di < chart.data.datasets.length; di++) {
        const meta = chart.getDatasetMeta(di);
        if (!meta || meta.type !== "bar" || meta.hidden) continue;
        const ds = chart.data.datasets[di];
        for (let i = 0; i < meta.data.length; i++) {
          const el = meta.data[i];
          if (!el) continue;
          const raw = ds.data[i];
          const v =
            typeof raw === "object" && raw != null
              ? Number(raw.x ?? raw.y ?? raw)
              : Number(raw);
          if (!Number.isFinite(v)) continue;
          const text = String(fmtFn(v));
          const props = el.getProps(["x", "y", "base"], true);
          const textW = ctx.measureText(text).width;
          const gap = 6;
          if (horizontal) {
            let tx = props.x + gap;
            ctx.textAlign = "left";
            let color = chrome.label;
            if (tx + textW > chartArea.right - 1) {
              tx = props.x - gap;
              ctx.textAlign = "right";
              color = isDark() ? "rgba(0,0,0,0.82)" : "rgba(255,255,255,0.96)";
            }
            ctx.fillStyle = color;
            ctx.fillText(text, tx, props.y);
          } else {
            ctx.textAlign = "center";
            let ty = props.y - gap;
            let color = chrome.label;
            ctx.textBaseline = "bottom";
            if (ty - fontSize < chartArea.top) {
              ty = props.y + gap;
              ctx.textBaseline = "top";
              color = isDark() ? "rgba(0,0,0,0.82)" : "rgba(255,255,255,0.96)";
            }
            ctx.fillStyle = color;
            ctx.fillText(text, props.x, ty);
          }
        }
      }
      ctx.restore();
    },
  };

  function ensureBarReveal(key, total) {
    if (total <= 0) {
      state.barReveal[key] = 0;
      return 0;
    }
    // Always fill at least the first page (or the whole list when it fits).
    // Otherwise a prior 1-item render can leave reveal stuck at 1 after filters grow.
    const page = Math.min(BAR_PAGE, total);
    if (state.barReveal[key] == null || state.barReveal[key] < page) {
      state.barReveal[key] = page;
    }
    state.barReveal[key] = Math.min(Math.max(state.barReveal[key], page), total);
    return state.barReveal[key];
  }

  function setChartBoxHeight(boxEl, n) {
    if (!boxEl) return;
    // Grow with row count so Chart.js does not autoSkip category labels.
    // Page scroll handles tall lists — do not clamp to a short fixed height.
    const row = isCompactFilterUi() ? 26 : 28;
    const px = Math.max(180, 40 + Math.max(1, n) * row);
    boxEl.style.height = `${px}px`;
    boxEl.classList.add("expandable");
  }

  function renderMoreControls(hostId, key, shown, total, rerender) {
    const host = $(hostId);
    if (!host) return;
    if (total <= BAR_PAGE && shown >= total) {
      host.innerHTML = "";
      return;
    }
    const remaining = Math.max(0, total - shown);
    const parts = [];
    if (remaining > 0) {
      parts.push(
        `<button type="button" class="btn secondary" data-more="1">Show more (${fmt(remaining)} left)</button>`
      );
    }
    if (shown > BAR_PAGE) {
      parts.push(`<button type="button" class="btn secondary" data-less="1">Show less</button>`);
    }
    host.innerHTML = parts.join("");
    host.querySelector("[data-more]")?.addEventListener("click", () => {
      state.barReveal[key] = Math.min(total, (state.barReveal[key] || BAR_PAGE) + BAR_PAGE);
      rerender();
    });
    host.querySelector("[data-less]")?.addEventListener("click", () => {
      state.barReveal[key] = BAR_PAGE;
      rerender();
    });
  }

  /** Horizontal bar chart with progressive disclosure.
   * Default: largest value at top. Pass preserveOrder for chronological axes. */
  function themeFocusColor() {
    // Distinct from the default teal theme bars so the focused theme stands out.
    return palette().blue;
  }

  function renderExpandableHBar({
    key,
    canvasSel,
    boxSel,
    moreSel,
    items,
    labelOf,
    valueOf,
    valueLabel,
    color,
    colors,
    colorOf,
    onClick,
    preserveOrder = false,
  }) {
    const ordered = preserveOrder
      ? items.slice()
      : items
          .slice()
          .sort(
            (a, b) =>
              valueOf(b) - valueOf(a) ||
              String(labelOf(a)).localeCompare(String(labelOf(b)))
          );
    const total = ordered.length;
    const shown = ensureBarReveal(key, total);
    const visible = ordered.slice(0, shown);
    setChartBoxHeight($(boxSel), visible.length || 1);
    destroyChart(key);
    const canvas = $(canvasSel);
    if (!canvas) return;
    const label = valueLabel || metricValueLabel();
    const compact = isCompactFilterUi();
    const chrome = chartChrome();
    // Attach before new Chart so the first afterDatasetsDraw can format values.
    canvas.__formatBarEnd = (v) => formatBarEndValue(v, label);
    const barColors = colorOf
      ? visible.map((d) => colorOf(d))
      : colors
        ? visible.map((_, i) => colors[i % colors.length])
        : color || palette().teal;
    state.charts[key] = new Chart(canvas, {
      type: "bar",
      plugins: [barValueLabelsPlugin],
      data: {
        labels: visible.map((d) => {
          const lab = String(labelOf(d) || "");
          return lab.length > 34 ? lab.slice(0, 32) + "…" : lab;
        }),
        datasets: [
          {
            label,
            data: visible.map(valueOf),
            backgroundColor: barColors,
            borderRadius: 5,
            maxBarThickness: 22,
          },
        ],
      },
      options: baseChartOptions({
        indexAxis: "y",
        // Resolve hover/tooltip by row (Y), not nearest bar tip length.
        interaction: { mode: "nearest", axis: "y", intersect: false },
        // Clicks/taps are handled on the canvas below — keep Chart.js off the
        // click path so it cannot race or steal the gesture.
        events: ["mousemove", "mouseout", "touchstart", "touchmove"],
        // Room for end-of-bar value labels (grids + value-axis ticks removed).
        layout: {
          padding: {
            top: compact ? 4 : 2,
            right: compact ? 40 : 48,
            bottom: compact ? 2 : 2,
            left: compact ? 2 : 0,
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => {
                const v = ctx.parsed.x ?? ctx.parsed.y ?? ctx.raw;
                return `${label}: ${formatBarEndValue(v, label)}`;
              },
            },
          },
        },
        scales: {
          // Value axis: numbers live on the bars — hide ticks + grid.
          x: {
            beginAtZero: true,
            grace: "14%",
            ticks: { display: false },
            grid: { display: false },
            border: { display: false },
          },
          // Category axis: keep names; no grid lines.
          y: {
            grid: { display: false },
            border: { display: false },
            ticks: {
              color: chrome.muted,
              padding: compact ? 4 : 0,
              autoSkip: false,
              font: { family: "Figtree, sans-serif", size: compact ? 11 : 12 },
            },
          },
        },
      }),
    });
    state.charts[key].$formatBarEnd = (v) => formatBarEndValue(v, label);
    // Bind taps ourselves: map by category Y so label taps and short bars hit
    // the row under the finger, not the nearest long bar tip.
    if (onClick) {
      const chart = state.charts[key];
      let lastTs = 0;
      const handler = (native) => {
        // Ignore superseded charts and taps while a newer filter render owns UI.
        if (state.charts[key] !== chart) return;
        if (document.body.classList.contains("is-filtering") && state._renderGen !== chart.$bindGen) {
          return;
        }
        if (!chart?.scales?.y) return;
        const rect = canvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        // Chart.js layout / getValueForPixel use CSS pixels (chart.height),
        // NOT the canvas backing-store size (canvas.height = css * dpr).
        // Using canvas.height on a 3× phone mapped China → Middle East (+2).
        let y;
        if (native.target === canvas && typeof native.offsetY === "number") {
          y = native.offsetY * (chart.height / rect.height);
        } else {
          const clientY = native.clientY ?? native.changedTouches?.[0]?.clientY;
          if (clientY == null) return;
          y = ((clientY - rect.top) / rect.height) * chart.height;
        }
        const idx = Math.round(chart.scales.y.getValueForPixel(y));
        if (!Number.isFinite(idx) || idx < 0 || idx >= visible.length) return;
        const now = performance.now();
        // pointerup + click can both fire; accept one gesture.
        if (now - lastTs < 350) return;
        lastTs = now;
        onClick(visible[idx], idx);
      };
      chart.$hBarClick = handler;
      chart.$bindGen = state._renderGen;
      canvas.addEventListener("click", handler);
      canvas.addEventListener("pointerup", handler);
    }
    renderMoreControls(moreSel, key, shown, total, () =>
      renderExpandableHBar({
        key,
        canvasSel,
        boxSel,
        moreSel,
        items,
        labelOf,
        valueOf,
        valueLabel,
        color,
        colors,
        colorOf,
        onClick,
        preserveOrder,
      })
    );
  }

  function countryForEpisode(e) {
    const name = e?.p || "Unknown";
    const author = e?.a || "";
    const byPod = state.countriesDoc?.byPodcast || {};
    const byAuthor = state.countriesDoc?.byAuthor || {};
    return byPod[name] || byAuthor[author] || "Unknown";
  }

  function bump(map, key, amount) {
    map[key] = (map[key] || 0) + amount;
  }

  function seriesFromMap(map, useHours) {
    const keys = Object.keys(map).sort();
    const values = keys.map((k) => (useHours ? Math.round(map[k] * 10) / 10 : map[k]));
    const points = keys.map((k, i) => ({ month: k, count: values[i] }));
    const rolling = points.map((_, i) => {
      const slice = points.slice(Math.max(0, i - 2), i + 1);
      const sum = slice.reduce((acc, m) => acc + m.count, 0);
      return Math.round((sum / slice.length) * 10) / 10;
    });
    let running = 0;
    const cumulative = points.map((m) => {
      running += m.count;
      return {
        month: m.month,
        total: useHours ? Math.round(running * 10) / 10 : running,
      };
    });
    return { points, rolling, cumulative };
  }

  function ensureChartStats(opts = {}) {
    const ignoreTheme = !!opts.ignoreTheme;
    const trendGrain = themeTrendGrain();
    const key = `${chartPeriodKey()}|theme:${ignoreTheme ? "any" : "on"}|g:${trendGrain}`;
    if (!state._chartStatsCache) state._chartStatsCache = Object.create(null);
    if (state._chartStatsCache[key]) {
      state._chartStats = state._chartStatsCache[key];
      state._chartStatsKey = key;
      return state._chartStats;
    }

    const byPodcastHours = Object.create(null);
    const byPodcastCount = Object.create(null);
    const byYearHours = Object.create(null);
    const byYearCount = Object.create(null);
    const byMonthHours = Object.create(null);
    const byMonthCount = Object.create(null);
    const byDateHours = Object.create(null);
    const byDateCount = Object.create(null);
    const byFolderHours = Object.create(null);
    const byFolderCount = Object.create(null);
    const byCountryHours = Object.create(null);
    const byCountryCount = Object.create(null);
    const byStatusHours = Object.create(null);
    const byStatusCount = Object.create(null);
    const byThemeHours = Object.create(null);
    const byThemeCount = Object.create(null);
    const byThemeYearHours = Object.create(null);
    const byThemeYearCount = Object.create(null);
    const byThemeMonthHours = Object.create(null);
    const byThemeMonthCount = Object.create(null);
    const byThemeDateHours = Object.create(null);
    const byThemeDateCount = Object.create(null);
    const hourHours = Array.from({ length: 24 }, () => 0);
    const weekdayHours = Array.from({ length: 7 }, () => 0);
    const hourCounts = Array.from({ length: 24 }, () => 0);
    const weekdayCounts = Array.from({ length: 7 }, () => 0);
    const yearMinutes = Object.create(null);
    const yearMinuteSamples = Object.create(null);

    let episodeCount = 0;
    let hoursTotal = 0;
    let progressSum = 0;
    let progressN = 0;
    const finishLagDays = [];
    const eps = state.episodes || [];
    const matchOpts = ignoreTheme ? { theme: "" } : null;
    const matchedIdxs = matchedEpisodeIndexes(matchOpts);
    const epHours = state._epHours;
    const epCountry = state._epCountry;
    const epHour = state._epHour;
    const epWeekday = state._epWeekday;
    const needThemeYear = trendGrain === "year";
    const needThemeMonth = trendGrain === "month";
    const needThemeDate = trendGrain === "day";
    const themeFilter = ignoreTheme ? "" : (state.chartPeriod.theme || "");
    for (let n = 0; n < matchedIdxs.length; n++) {
      const i = matchedIdxs[n];
      const e = eps[i];
      episodeCount += 1;
      const hFull = epHours ? epHours[i] : parseDurHours(e.dur);
      // When a theme is selected, hours are that theme's share of the episode —
      // not the full runtime credited to every co-tagged topic.
      const h = themeFilter ? hFull * themeWeightForIndex(i, themeFilter) : hFull;
      hoursTotal += h;
      if (e.prog !== "" && e.prog != null && !Number.isNaN(Number(e.prog))) {
        progressSum += Number(e.prog);
        progressN += 1;
      }
      // Release → fully listened lag (Played only; pub date vs listen timestamp).
      if (e.st === "Played" && e.pub && e.t) {
        const pubStr = String(e.pub);
        const pubMs = Date.parse(
          pubStr.length === 10 ? `${pubStr}T00:00:00Z` : pubStr
        );
        const listen = parseListenUtc(e.t);
        if (listen && Number.isFinite(pubMs)) {
          const lag = (listen.getTime() - pubMs) / 86400000;
          if (lag >= 0) finishLagDays.push(lag);
        }
      }
      const name = e.p || "Unknown";
      const year = e.y != null && e.y !== "" ? String(e.y) : String(e.d || "").slice(0, 4);
      const folder = e.f || "Ungrouped";
      const month = String(e.d || "").slice(0, 7);
      const status = e.st || "Unknown";
      const date = e.d || "";

      bump(byPodcastHours, name, h);
      bump(byPodcastCount, name, 1);
      if (year) {
        bump(byYearHours, year, h);
        bump(byYearCount, year, 1);
        if (h > 0) {
          bump(yearMinutes, year, h * 60);
          bump(yearMinuteSamples, year, 1);
        }
      }
      bump(byFolderHours, folder, h);
      bump(byFolderCount, folder, 1);
      const country = epCountry ? epCountry[i] : countryForEpisode(e);
      bump(byCountryHours, country, h);
      bump(byCountryCount, country, 1);
      if (month.length === 7) {
        bump(byMonthHours, month, h);
        bump(byMonthCount, month, 1);
      }
      bump(byStatusHours, status, h);
      bump(byStatusCount, status, 1);
      if (date) {
        bump(byDateHours, date, h);
        bump(byDateCount, date, 1);
      }

      if (epHour && epWeekday) {
        const hr = epHour[i];
        const wd = epWeekday[i];
        if (hr >= 0) {
          hourHours[hr] += h;
          hourCounts[hr] += 1;
        }
        if (wd >= 0) {
          weekdayHours[wd] += h;
          weekdayCounts[wd] += 1;
        }
      } else {
        const d = parseListenUtc(e.t);
        if (d) {
          const loc = sydneyHourAndWeekday(d);
          if (loc.hour != null) {
            hourHours[loc.hour] += h;
            hourCounts[loc.hour] += 1;
          }
          if (loc.weekday != null) {
            weekdayHours[loc.weekday] += h;
            weekdayCounts[loc.weekday] += 1;
          }
        }
      }

      const themes = (state.episodeThemes && state.episodeThemes[i]) || [];
      for (const tid of themes) {
        const th = hFull * themeWeightForIndex(i, tid);
        bump(byThemeHours, tid, th);
        bump(byThemeCount, tid, 1);
        if (needThemeYear && year) {
          if (!byThemeYearHours[tid]) byThemeYearHours[tid] = Object.create(null);
          if (!byThemeYearCount[tid]) byThemeYearCount[tid] = Object.create(null);
          bump(byThemeYearHours[tid], year, th);
          bump(byThemeYearCount[tid], year, 1);
        } else if (needThemeMonth && month.length === 7) {
          if (!byThemeMonthHours[tid]) byThemeMonthHours[tid] = Object.create(null);
          if (!byThemeMonthCount[tid]) byThemeMonthCount[tid] = Object.create(null);
          bump(byThemeMonthHours[tid], month, th);
          bump(byThemeMonthCount[tid], month, 1);
        } else if (needThemeDate && date) {
          if (!byThemeDateHours[tid]) byThemeDateHours[tid] = Object.create(null);
          if (!byThemeDateCount[tid]) byThemeDateCount[tid] = Object.create(null);
          bump(byThemeDateHours[tid], date, th);
          bump(byThemeDateCount[tid], date, 1);
        }
      }
    }

    const avgDurationByYear = Object.keys(yearMinutes)
      .sort()
      .map((year) => ({
        year: Number(year),
        avgMinutes:
          Math.round(((yearMinutes[year] || 0) / (yearMinuteSamples[year] || 1)) * 10) / 10,
      }));

    const hoursRounded = Math.round(hoursTotal * 10) / 10;
    state._chartStats = {
      episodeCount,
      hoursTotal: hoursRounded,
      podcastCount: Object.keys(byPodcastCount).length,
      avgEpisodeMinutes:
        episodeCount > 0 ? Math.round(((hoursTotal * 60) / episodeCount) * 10) / 10 : null,
      avgProgressPct:
        progressN > 0 ? Math.round((progressSum / progressN) * 10) / 10 : null,
      medianFinishLagDays: medianOf(finishLagDays),
      byPodcastHours,
      byPodcastCount,
      byYearHours,
      byYearCount,
      byMonthHours,
      byMonthCount,
      byDateHours,
      byDateCount,
      byFolderHours,
      byFolderCount,
      byCountryHours,
      byCountryCount,
      byStatusHours,
      byStatusCount,
      byThemeHours,
      byThemeCount,
      byThemeYearHours,
      byThemeYearCount,
      byThemeMonthHours,
      byThemeMonthCount,
      byThemeDateHours,
      byThemeDateCount,
      hourHours,
      weekdayHours,
      hourCounts,
      weekdayCounts,
      avgDurationByYear,
    };
    state._chartStatsKey = key;
    state._chartStatsCache[key] = state._chartStats;
    return state._chartStats;
  }

  /** Backward-compatible alias used by older call sites during the transition. */
  function ensureDurationStats() {
    const s = ensureChartStats();
    return {
      byPodcast: s.byPodcastHours,
      byPodcastCount: s.byPodcastCount,
      byYear: s.byYearHours,
      byFolder: s.byFolderHours,
      byMonth: s.byMonthHours,
      byStatus: s.byStatusHours,
      byDate: s.byDateHours,
      byTheme: s.byThemeHours,
      byThemeYear: s.byThemeYearHours,
      hourHours: s.hourHours,
      weekdayHours: s.weekdayHours,
      hourCounts: s.hourCounts,
      weekdayCounts: s.weekdayCounts,
      monthly: seriesFromMap(s.byMonthHours, true).points,
      monthlyRolling3: seriesFromMap(s.byMonthHours, true).rolling,
      cumulative: seriesFromMap(s.byMonthHours, true).cumulative,
      yoyByMonth: (() => {
        const yoy = Object.create(null);
        for (const [ym, hours] of Object.entries(s.byMonthHours)) {
          const [y, mo] = ym.split("-");
          if (!yoy[mo]) yoy[mo] = Object.create(null);
          yoy[mo][y] = Math.round(hours * 10) / 10;
        }
        return yoy;
      })(),
    };
  }

  function metricSeriesFromMonthMap(hoursMap, countMap, keys = null) {
    const map = metricIsHours() ? hoursMap : countMap;
    const useHours = metricIsHours();
    if (keys && keys.length) return seriesFromMapKeys(map, keys, useHours);
    return seriesFromMap(map, useHours);
  }

  function yoyFromMonthMap(hoursMap, countMap) {
    const src = metricIsHours() ? hoursMap : countMap;
    const yoy = Object.create(null);
    for (const [ym, val] of Object.entries(src)) {
      const [y, mo] = ym.split("-");
      if (!yoy[mo]) yoy[mo] = Object.create(null);
      yoy[mo][y] = metricIsHours() ? Math.round(val * 10) / 10 : val;
    }
    return yoy;
  }

  function baseChartOptions(extra = {}) {
    const chrome = chartChrome();
    const compact = isCompactFilterUi();
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      layout: {
        padding: compact
          ? { top: 4, right: 6, bottom: 2, left: 2 }
          : { top: 0, right: 0, bottom: 0, left: 0 },
      },
      plugins: {
        legend: {
          labels: {
            color: chrome.label,
            font: { family: "Figtree, sans-serif", size: 12 },
            boxWidth: 12,
          },
        },
        tooltip: {
          backgroundColor: chrome.tooltipBg,
          titleFont: { family: "Figtree, sans-serif" },
          bodyFont: { family: "Figtree, sans-serif" },
        },
      },
      scales: {
        x: {
          ticks: {
            color: chrome.muted,
            maxRotation: 0,
            autoSkipPadding: 12,
            padding: compact ? 4 : 0,
          },
          grid: { color: chrome.grid },
        },
        y: {
          beginAtZero: true,
          ticks: { color: chrome.muted, padding: compact ? 4 : 0 },
          grid: { color: chrome.grid },
        },
      },
      ...extra,
    };
  }

  function rerenderCharts() {
    if (!state.agg) return;
    renderTrendChart();
    renderCumulativeChart();
    renderYearChart();
    renderYoYChart();
    renderTopPodcastsChart();
    renderWeekdayHourCharts();
    renderFolderStatusCharts();
    renderCountryChart();
    renderDurationChart();
    renderThemeChart();
    renderThemeYearChart();
    renderThemePodcastCharts();
  }

  async function hardRefresh() {
    const btn = $("#hardRefresh");
    if (btn) {
      btn.disabled = true;
      const label = btn.querySelector(".refresh-label");
      if (label) label.textContent = "Refreshing…";
      else btn.setAttribute("aria-label", "Refreshing…");
    }
    try {
      if ("serviceWorker" in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map((r) => r.unregister()));
      }
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
    } catch (_) {}
    const url = new URL(location.href);
    url.searchParams.set("_", String(Date.now()));
    location.replace(url.toString());
  }

  function peakFromMap(map, useHours) {
    let bestKey = "";
    let bestVal = -1;
    for (const [k, v] of Object.entries(map || {})) {
      const n = Number(v) || 0;
      if (n > bestVal) {
        bestVal = n;
        bestKey = k;
      }
    }
    if (!bestKey || bestVal < 0) return null;
    return {
      key: bestKey,
      value: useHours ? Math.round(bestVal * 10) / 10 : bestVal,
    };
  }

  /** Median of a numeric array. Mutates a copy via sort; returns null if empty. */
  function medianOf(values) {
    const n = values?.length || 0;
    if (!n) return null;
    const sorted = values.slice().sort((a, b) => a - b);
    const mid = Math.floor(n / 2);
    if (n % 2) return sorted[mid];
    return (sorted[mid - 1] + sorted[mid]) / 2;
  }

  /** Compact duration for hero stats — hours below 1 day, else days. */
  function formatLagDuration(days) {
    if (days == null || !Number.isFinite(days)) return "—";
    if (days < 1) {
      const hours = Math.round(days * 24 * 10) / 10;
      return `${hours}h`;
    }
    const rounded = Math.round(days * 10) / 10;
    return `${rounded}d`;
  }

  /** MMM YYYY — e.g. Jun 2025 (month buckets have no day). */
  function formatMonthKey(ym) {
    const s = String(ym || "");
    if (s.length < 7) return s;
    const y = s.slice(0, 4);
    const m = s.slice(5, 7);
    return `${MONTH_SHORT[m] || m} ${y}`;
  }

  /** DD MMM YYYY — e.g. 07 Mar 2019. Month-only keys fall back to MMM YYYY. */
  function formatDateKey(iso) {
    const s = String(iso || "").trim();
    if (s.length < 10) return formatMonthKey(s);
    const y = s.slice(0, 4);
    const m = s.slice(5, 7);
    const d = s.slice(8, 10).padStart(2, "0");
    return `${d} ${MONTH_SHORT[m] || m} ${y}`;
  }

  /** Alias — same DD MMM YYYY standard as formatDateKey. */
  function formatDateShort(iso) {
    return formatDateKey(iso);
  }

  /** Format any ISO date / YYYY-MM / raw timestamp for UI display. */
  function formatUiDate(value) {
    const s = String(value || "").trim();
    if (!s) return "";
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return formatDateKey(s.slice(0, 10));
    if (/^\d{4}-\d{2}$/.test(s)) return formatMonthKey(s);
    return s;
  }

  function daysInCalendarMonth(year, month) {
    const y = Number(year);
    const m = Number(month);
    if (!Number.isFinite(y) || !Number.isFinite(m) || m < 1 || m > 12) return 0;
    return new Date(y, m, 0).getDate();
  }

  function enumerateMonthKeys(startYm, endYm) {
    const start = String(startYm || "");
    const end = String(endYm || "");
    if (!/^\d{4}-\d{2}$/.test(start) || !/^\d{4}-\d{2}$/.test(end) || start > end) {
      return [];
    }
    const keys = [];
    let y = Number(start.slice(0, 4));
    let m = Number(start.slice(5, 7));
    const ey = Number(end.slice(0, 4));
    const em = Number(end.slice(5, 7));
    while (y < ey || (y === ey && m <= em)) {
      keys.push(`${y}-${String(m).padStart(2, "0")}`);
      m += 1;
      if (m > 12) {
        m = 1;
        y += 1;
      }
    }
    return keys;
  }

  function enumerateDayKeys(year, month) {
    const y = String(year || "");
    const mo = String(month || "").padStart(2, "0");
    const n = daysInCalendarMonth(y, mo);
    const keys = [];
    for (let d = 1; d <= n; d++) {
      keys.push(`${y}-${mo}-${String(d).padStart(2, "0")}`);
    }
    return keys;
  }

  function historyYearKeys() {
    const years = (state.agg?.meta?.years || [])
      .map((y) => Number(y))
      .filter((y) => Number.isFinite(y))
      .sort((a, b) => a - b);
    if (!years.length) return [];
    const keys = [];
    for (let y = years[0]; y <= years[years.length - 1]; y++) keys.push(String(y));
    return keys;
  }

  /** Full calendar axis for the sticky time filter (not “keys that have listens”). */
  function periodAxisKeys() {
    if (!dateRangeActive()) {
      const from = String(state.agg?.meta?.perEpisodeHistoryFrom || "").slice(0, 7);
      const yearKeys = historyYearKeys();
      if (/^\d{4}-\d{2}$/.test(from) && yearKeys.length) {
        const endYear = yearKeys[yearKeys.length - 1];
        const now = new Date();
        const end =
          Number(endYear) === now.getFullYear()
            ? `${endYear}-${String(now.getMonth() + 1).padStart(2, "0")}`
            : `${endYear}-12`;
        // Trend/cumulative charts prefer month grain across all-time.
        return { grain: "month", keys: enumerateMonthKeys(from, end) };
      }
      return { grain: "year", keys: yearKeys };
    }
    const { from, to } = effectiveDateRange();
    if (!from || !to) return { grain: "year", keys: historyYearKeys() };
    if (from === to) return { grain: "day", keys: [from] };
    const span = daysBetweenISO(from, to);
    if (span != null && span <= 62) {
      return { grain: "day", keys: enumerateDayKeysInclusive(from, to) };
    }
    return {
      grain: "month",
      keys: enumerateMonthKeys(from.slice(0, 7), to.slice(0, 7)),
    };
  }

  function seriesFromMapKeys(map, keys, useHours) {
    const points = keys.map((k) => {
      const raw = Number(map?.[k] || 0);
      const count = useHours ? Math.round(raw * 10) / 10 : raw;
      return { month: k, count };
    });
    const rolling = points.map((_, i) => {
      const slice = points.slice(Math.max(0, i - 2), i + 1);
      const sum = slice.reduce((acc, m) => acc + m.count, 0);
      return Math.round((sum / slice.length) * 10) / 10;
    });
    let running = 0;
    const cumulative = points.map((m) => {
      running += m.count;
      return {
        month: m.month,
        total: useHours ? Math.round(running * 10) / 10 : running,
      };
    });
    return { points, rolling, cumulative };
  }

  function listeningDateBounds(stats) {
    const dates = Object.keys(stats.byDateCount || {}).sort();
    if (!dates.length) return null;
    return { from: dates[0], to: dates[dates.length - 1] };
  }

  function avgEpisodesPerDay(stats) {
    const dates = Object.keys(stats.byDateCount || {}).sort();
    if (!dates.length || !stats.episodeCount) return null;
    const first = Date.parse(`${dates[0]}T00:00:00Z`);
    const last = Date.parse(`${dates[dates.length - 1]}T00:00:00Z`);
    if (!Number.isFinite(first) || !Number.isFinite(last) || last < first) return null;
    const days = Math.round((last - first) / 86400000) + 1;
    if (days < 1) return null;
    return Math.round((stats.episodeCount / days) * 10) / 10;
  }

  function renderHeroStats() {
    if (!state.agg || !$("#heroStats")) return;
    const stats = ensureChartStats();
    const hours = metricIsHours();
    const bounds = listeningDateBounds(stats);
    const monthPeak = peakFromMap(
      hours ? stats.byMonthHours : stats.byMonthCount,
      hours
    );
    const dayPeak = peakFromMap(hours ? stats.byDateHours : stats.byDateCount, hours);
    const avgDay = avgEpisodesPerDay(stats);
    const monthValue = monthPeak
      ? `${formatMonthKey(monthPeak.key)} · ${fmtMetric(monthPeak.value)}${hours ? "h" : ""}`
      : "—";
    const dayValue = dayPeak
      ? `${formatDateKey(dayPeak.key)} · ${fmtMetric(dayPeak.value)}${hours ? "h" : ""}`
      : "—";

    const meta = $("#exportedAt");
    if (meta) {
      meta.textContent = bounds
        ? `Stats from ${formatUiDate(bounds.from)} and ${formatUiDate(bounds.to)}`
        : "";
    }

    // One 3×3 grid (no separate insights strip) so rows share the same card.
    const items = [
      ["Episodes", fmt(stats.episodeCount)],
      ["Podcasts", fmt(stats.podcastCount)],
      ["Hours", fmtHours(stats.hoursTotal)],
      [
        "Avg length",
        stats.avgEpisodeMinutes != null ? `${stats.avgEpisodeMinutes}m` : "—",
      ],
      [
        "Finish rate",
        stats.avgProgressPct != null ? `${stats.avgProgressPct}%` : "—",
      ],
      ["Median finish lag", formatLagDuration(stats.medianFinishLagDays)],
      ["Busiest month", monthValue],
      ["Most active day", dayValue],
      ["Avg episodes / day", avgDay != null ? String(avgDay) : "—"],
    ];
    $("#heroStats").innerHTML = items
      .map(([k, v]) => {
        const compact = String(v).length > 10 ? " stat-value-compact" : "";
        return `<div class="stat"><b class="${compact.trim()}">${escapeHtml(v)}</b><span>${escapeHtml(k)}</span></div>`;
      })
      .join("");

    const strip = $("#insightStrip");
    if (strip) {
      strip.hidden = true;
      strip.innerHTML = "";
    }
  }

  function trendSeries() {
    const stats = ensureChartStats();
    const axis = periodAxisKeys();
    const daily = axis.grain === "day";
    if (daily) {
      return metricSeriesFromMonthMap(stats.byDateHours, stats.byDateCount, axis.keys);
    }
    if (axis.grain === "month") {
      return metricSeriesFromMonthMap(stats.byMonthHours, stats.byMonthCount, axis.keys);
    }
    // Year grain (rare for the line charts) — fall back to months in history span.
    if (!chartPeriodActive() && !metricIsHours()) {
      // Prefer the filled calendar span so empty months stay visible.
      const filled = metricSeriesFromMonthMap(
        stats.byMonthHours,
        stats.byMonthCount,
        periodAxisKeys().keys
      );
      if (filled.points.length) return filled;
      const monthly = state.agg.monthly || [];
      return {
        points: monthly,
        rolling: state.agg.monthlyRolling3 || [],
        cumulative: state.agg.cumulative || [],
      };
    }
    return metricSeriesFromMonthMap(stats.byMonthHours, stats.byMonthCount, axis.keys);
  }

  function renderTrendChart() {
    const hours = metricIsHours();
    const daily = periodAxisKeys().grain === "day";
    const { points, rolling } = trendSeries();
    destroyChart("trend");
    const ctx = $("#trendChart");
    const datasets = [
      {
        label: hours
          ? daily
            ? "Hours / day"
            : "Hours / month"
          : daily
            ? "Episodes / day"
            : "Episodes / month",
        data: points.map((m) => m.count),
        borderColor: palette().blue,
        backgroundColor: "rgba(0,122,255,.14)",
        fill: true,
        tension: 0.28,
        pointRadius: daily ? 2 : 0,
        borderWidth: 2.2,
      },
    ];
    if (!daily && rolling.length) {
      datasets.push({
        label: "3-month average",
        data: rolling,
        borderColor: palette().amber,
        backgroundColor: "transparent",
        tension: 0.28,
        pointRadius: 0,
        borderWidth: 2.4,
        borderDash: [6, 4],
      });
    }
    state.charts.trend = new Chart(ctx, {
      type: "line",
      data: {
        labels: points.map((m) => formatUiDate(m.month)),
        datasets,
      },
      options: baseChartOptions({
        plugins: {
          ...baseChartOptions().plugins,
          title: { display: false },
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmtMetric(ctx.parsed.y)}`,
            },
          },
        },
      }),
    });
  }

  function renderCumulativeChart() {
    const hours = metricIsHours();
    const { cumulative } = trendSeries();
    destroyChart("cum");
    state.charts.cum = new Chart($("#cumChart"), {
      type: "line",
      data: {
        labels: cumulative.map((d) => formatUiDate(d.month)),
        datasets: [
          {
            label: hours ? "Cumulative hours" : "Cumulative episodes",
            data: cumulative.map((d) => d.total),
            borderColor: palette().navy,
            backgroundColor: "rgba(88,86,214,.12)",
            fill: true,
            tension: 0.2,
            pointRadius: 0,
            borderWidth: 2.2,
          },
        ],
      },
      options: baseChartOptions({
        plugins: {
          ...baseChartOptions().plugins,
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmtMetric(ctx.parsed.y)}`,
            },
          },
        },
      }),
    });
  }

  function yearChartItems() {
    const stats = ensureChartStats();
    const hours = metricIsHours();
    const axis = periodAxisKeys();
    if (axis.grain === "day") {
      const src = hours ? stats.byDateHours : stats.byDateCount;
      return axis.keys.map((date) => {
        const raw = src[date] || 0;
        const label = formatDateKey(date);
        return {
          year: label,
          label,
          count: hours ? Math.round(raw * 10) / 10 : raw,
        };
      });
    }
    if (axis.grain === "month" && dateRangeActive()) {
      const src = hours ? stats.byMonthHours : stats.byMonthCount;
      return axis.keys.map((ym) => {
        const raw = src[ym] || 0;
        const label = formatMonthKey(ym);
        return {
          year: label,
          label,
          count: hours ? Math.round(raw * 10) / 10 : raw,
        };
      });
    }
    // All-time (or non-time filters): one bar per history year, including empty years.
    const src = hours ? stats.byYearHours : stats.byYearCount;
    const yearKeys = historyYearKeys();
    if (yearKeys.length) {
      return yearKeys.map((year) => {
        const raw = src[year] || 0;
        return {
          year: Number(year),
          label: String(year),
          count: hours ? Math.round(raw * 10) / 10 : raw,
        };
      });
    }
    if (!hours && !chartPeriodActive()) {
      return (state.agg.yearly || []).map((d) => ({
        year: d.year,
        label: String(d.year),
        count: d.count,
      }));
    }
    return Object.keys(src)
      .sort((a, b) => Number(a) - Number(b))
      .map((year) => ({
        year: Number(year),
        label: String(year),
        count: hours ? Math.round(src[year] * 10) / 10 : src[year],
      }));
  }

  function renderYearChart() {
    renderExpandableHBar({
      key: "year",
      canvasSel: "#yearChart",
      boxSel: "#yearChartBox",
      moreSel: "#yearChartMore",
      items: yearChartItems(),
      labelOf: (d) => d.label || String(d.year),
      valueOf: (d) => d.count,
      color: palette().blue,
      preserveOrder: true,
    });
  }

  function topPodcastItems() {
    const stats = ensureChartStats();
    return Object.keys(stats.byPodcastCount).map((name) => ({
      name,
      count: stats.byPodcastCount[name] || 0,
      hours: stats.byPodcastHours[name] || 0,
    }));
  }

  function renderTopPodcastsChart() {
    const hours = metricIsHours();
    renderExpandableHBar({
      key: "top",
      canvasSel: "#topChart",
      boxSel: "#topChartBox",
      moreSel: "#topChartMore",
      items: topPodcastItems(),
      labelOf: (d) => d.name,
      valueOf: (d) => (hours ? d.hours : d.count),
      colors: categorical(),
      onClick: (d) => {
        if (!d?.name) return;
        patchChartPeriod({ podcast: d.name });
        goToSection("explorePanel");
      },
    });
  }

  const LISTEN_TZ = "Australia/Sydney";
  const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  function parseListenUtc(t) {
    if (!t) return null;
    const iso = t.includes("T") ? t : t.replace(" ", "T");
    const d = new Date(iso.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function sydneyHourAndWeekday(date) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: LISTEN_TZ,
      weekday: "short",
      hour: "numeric",
      hourCycle: "h23",
    }).formatToParts(date);
    const hour = Number(parts.find((p) => p.type === "hour")?.value ?? NaN);
    const wd = parts.find((p) => p.type === "weekday")?.value;
    const map = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
    return {
      hour: Number.isFinite(hour) ? hour % 24 : null,
      weekday: wd in map ? map[wd] : null,
    };
  }

  function listeningLocalStats() {
    const cacheKey = `${chartPeriodKey()}|${state.metric}`;
    if (state._localStats && state._localStats._key === cacheKey) return state._localStats;
    const hours = metricIsHours();
    if (Array.isArray(state.episodes) && state.episodes.length) {
      const stats = ensureChartStats();
      const hourVals = hours ? stats.hourHours : stats.hourCounts;
      const weekdayVals = hours ? stats.weekdayHours : stats.weekdayCounts;
      state._localStats = {
        _key: cacheKey,
        hour: hourVals.map((count, h) => ({ hour: h, count })),
        weekday: weekdayVals.map((count, i) => ({
          day: WEEKDAY_NAMES[i],
          count,
        })),
      };
      return state._localStats;
    }
    state._localStats = {
      _key: cacheKey,
      hour: state.agg?.hour || [],
      weekday: state.agg?.weekday || [],
    };
    return state._localStats;
  }

  function renderWeekdayHourCharts() {
    const { hour, weekday } = listeningLocalStats();
    const hours = metricIsHours();
    renderExpandableHBar({
      key: "weekday",
      canvasSel: "#weekdayChart",
      boxSel: "#weekdayChartBox",
      moreSel: "#weekdayChartMore",
      items: weekday || [],
      labelOf: (d) => d.day,
      valueOf: (d) => d.count,
      color: palette().vermillion,
      preserveOrder: true,
    });

    destroyChart("hour");
    state.charts.hour = new Chart($("#hourChart"), {
      type: "line",
      data: {
        labels: hour.map((d) => `${String(d.hour).padStart(2, "0")}:00`),
        datasets: [
          {
            label: hours ? "Hours by hour (AEST/AEDT)" : "Episodes by hour (AEST/AEDT)",
            data: hour.map((d) => d.count),
            borderColor: palette().teal,
            backgroundColor: "rgba(48,176,199,.14)",
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2,
          },
        ],
      },
      options: baseChartOptions({
        plugins: {
          legend: { display: false },
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmtMetric(ctx.parsed.y)}`,
            },
          },
        },
      }),
    });
  }

  function folderChartItems() {
    const stats = ensureChartStats();
    const src = metricIsHours() ? stats.byFolderHours : stats.byFolderCount;
    return Object.keys(src).map((name) => ({
      name,
      count: metricIsHours() ? Math.round(src[name] * 10) / 10 : src[name],
    }));
  }

  function statusChartItems() {
    const stats = ensureChartStats();
    const src = metricIsHours() ? stats.byStatusHours : stats.byStatusCount;
    const order = (state.agg.status || []).map((d) => d.name);
    const names = [
      ...order.filter((n) => src[n] != null),
      ...Object.keys(src).filter((n) => !order.includes(n)),
    ];
    return names.map((name) => ({
      name,
      count: metricIsHours() ? Math.round(src[name] * 10) / 10 : src[name],
    }));
  }

  function renderFolderStatusCharts() {
    const chrome = chartChrome();
    const statusItems = statusChartItems();
    renderExpandableHBar({
      key: "folder",
      canvasSel: "#folderChart",
      boxSel: "#folderChartBox",
      moreSel: "#folderChartMore",
      items: folderChartItems(),
      labelOf: (d) => d.name || "Ungrouped",
      valueOf: (d) => d.count,
      colors: categorical(),
    });

    destroyChart("status");
    state.charts.status = new Chart($("#statusChart"), {
      type: "doughnut",
      data: {
        labels: statusItems.map((d) => d.name),
        datasets: [
          {
            data: statusItems.map((d) => d.count),
            backgroundColor: [palette().teal, palette().amber, palette().slate, palette().blue],
            borderWidth: 2,
            borderColor: chrome.doughnutBorder,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "right",
            labels: {
              color: chrome.label,
              font: { family: "Figtree, sans-serif", size: 11 },
              boxWidth: 10,
            },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const v = ctx.parsed;
                return `${ctx.label}: ${fmtMetric(v)}`;
              },
            },
          },
        },
      },
    });
  }

  function countryChartItems() {
    const stats = ensureChartStats();
    const src = metricIsHours() ? stats.byCountryHours : stats.byCountryCount;
    return Object.keys(src).map((name) => ({
      name,
      count: metricIsHours() ? Math.round(src[name] * 10) / 10 : src[name],
    }));
  }

  function renderCountryChart() {
    if (!$("#countryChart")) return;
    renderExpandableHBar({
      key: "country",
      canvasSel: "#countryChart",
      boxSel: "#countryChartBox",
      moreSel: "#countryChartMore",
      items: countryChartItems(),
      labelOf: (d) => d.name || "Unknown",
      valueOf: (d) => d.count,
      colors: categorical(),
      onClick: (d) => {
        if (!d?.name) return;
        applyChartPeriod({
          from: state.chartPeriod.from,
          to: state.chartPeriod.to,
          preset: state.chartPeriod.preset,
          country: d.name,
        });
        goToSection("explorePanel");
      },
    });
  }

  function renderDurationChart() {
    const items =
      chartPeriodActive() || metricIsHours()
        ? ensureChartStats().avgDurationByYear
        : state.agg.avgDurationByYear || [];
    renderExpandableHBar({
      key: "dur",
      canvasSel: "#durChart",
      boxSel: "#durChartBox",
      moreSel: "#durChartMore",
      items,
      labelOf: (d) => String(d.year),
      valueOf: (d) => d.avgMinutes,
      valueLabel: "Avg minutes",
      color: palette().amber,
      preserveOrder: true,
    });
  }

  function yearsCoveredByDateRange() {
    if (!dateRangeActive()) {
      return (state.agg?.meta?.years || []).map(String).slice().reverse();
    }
    const { from, to } = effectiveDateRange();
    if (!from || !to) return [];
    const ys = [];
    for (let y = Number(from.slice(0, 4)); y <= Number(to.slice(0, 4)); y++) {
      ys.push(String(y));
    }
    return ys.reverse();
  }

  function renderYoYChart() {
    const hostNote = $("#yoyChartNote");
    const canvas = $("#yoyChart");
    const panel = canvas?.closest(".panel");
    // YoY comparison needs multi-month span — hide for short day-grain ranges.
    const axis = periodAxisKeys();
    if (axis.grain === "day") {
      destroyChart("yoy");
      if (panel) panel.hidden = true;
      return;
    }
    if (panel) panel.hidden = false;
    const stats = ensureChartStats();
    const yoy =
      chartPeriodActive() || metricIsHours()
        ? yoyFromMonthMap(stats.byMonthHours, stats.byMonthCount)
        : state.agg.yoyByMonth || {};
    const months = ["01","02","03","04","05","06","07","08","09","10","11","12"];
    const labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    let years = yearsCoveredByDateRange();
    if (!years.length) years = (state.agg.meta.years || []).slice().reverse();
    const dashes = [[], [6, 4], [2, 3], [8, 3, 2, 3], [], [6, 4], [2, 3], [8, 3, 2, 3]];
    if (hostNote && dateRangeActive() && years.length === 1) {
      hostNote.textContent = metricIsHours()
        ? `Month-by-month hours in ${years[0]}.`
        : `Month-by-month episodes in ${years[0]}.`;
    }
    destroyChart("yoy");
    state.charts.yoy = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: years.map((y, i) => ({
          label: String(y),
          data: months.map((m) => (yoy[m] && yoy[m][String(y)]) || 0),
          borderColor: categorical()[i % categorical().length],
          backgroundColor: "transparent",
          tension: 0.25,
          pointRadius: 2,
          pointHoverRadius: 5,
          borderWidth: 2.4,
          borderDash: dashes[i % dashes.length],
        })),
      },
      options: baseChartOptions({
        plugins: {
          ...baseChartOptions().plugins,
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmtMetric(ctx.parsed.y)}`,
            },
          },
        },
      }),
    });
  }

  function heatmapCells() {
    const stats = ensureChartStats();
    const hours = metricIsHours();
    const src = hours ? stats.byDateHours : stats.byDateCount;
    // Time-scoped filters: paint every calendar day in the selected period
    // when the span is short enough; otherwise show data days only.
    if (dateRangeActive()) {
      const { from, to } = effectiveDateRange();
      const span = daysBetweenISO(from, to);
      if (from && to && span != null && span <= 366) {
        const keys = enumerateDayKeysInclusive(from, to);
        return keys.map((date) => {
          const raw = src[date] || 0;
          return { date, count: hours ? Math.round(raw * 10) / 10 : raw };
        });
      }
      return Object.keys(src)
        .sort()
        .filter((date) => (!from || date >= from) && (!to || date <= to))
        .map((date) => ({
          date,
          count: hours ? Math.round(src[date] * 10) / 10 : src[date],
        }));
    }
    if (chartPeriodActive()) {
      // Non-time filters: keep data days only (no single calendar period to fill).
      return Object.keys(src)
        .sort()
        .map((date) => ({
          date,
          count: hours ? Math.round(src[date] * 10) / 10 : src[date],
        }));
    }
    const base = state.agg.heatmap || [];
    if (!hours) return base;
    return base.map((c) => ({
      date: c.date,
      count: Math.round((src[c.date] || 0) * 10) / 10,
    }));
  }

  function renderHeatmap() {
    const cells = heatmapCells();
    const host = $("#heatmap");
    if (!cells.length) {
      host.innerHTML = "";
      return;
    }
    const max = Math.max(...cells.map((c) => c.count), 1);
    const hours = metricIsHours();
    host.innerHTML = cells
      .map((c) => {
        let level = 0;
        if (c.count > 0) level = 1;
        if (c.count >= max * 0.25) level = 2;
        if (c.count >= max * 0.5) level = 3;
        if (c.count >= max * 0.75) level = 4;
        const unit = hours
          ? `${fmtHours(c.count)} hour${c.count === 1 ? "" : "s"}`
          : `${c.count} episode${c.count === 1 ? "" : "s"}`;
        return `<div class="heat-cell" data-level="${level}" title="${escapeHtml(formatUiDate(c.date))}: ${escapeHtml(unit)}"></div>`;
      })
      .join("");
  }

  function populateFilters() {
    syncPeriodControls();
  }

  function parentThemes() {
    return state.themesDoc?.themes || [];
  }

  function flatThemes() {
    return state.themesDoc?.flat || parentThemes();
  }

  function themeMetricInYears(t) {
    if (!t) return 0;
    // Theme browser stays navigable even when a theme is selected in the sticky bar.
    const stats = ensureChartStats({ ignoreTheme: true });
    return metricIsHours()
      ? stats.byThemeHours[t.id] || 0
      : stats.byThemeCount[t.id] || 0;
  }

  /** Themes with at least one matching episode under the sticky filters (theme facet ignored). */
  function themesPresentInFilter(themes) {
    return (themes || []).filter((t) => themeMetricInYears(t) > 0);
  }

  function themeMetricLabel(n) {
    return metricIsHours() ? `${fmtHours(n)}h` : fmt(n);
  }

  function sampleMatchesChartPeriod(s) {
    if (!s) return false;
    const d = String(s.d || "");
    // Samples lack theme indices / notes; match date/country/show/title/search text.
    return episodeMatchesChartPeriod(
      { d, y: d.slice(0, 4), p: s.p || "", a: "", st: "", e: s.e || "" },
      null,
      { theme: "", status: "" }
    );
  }

  function pruneInvisibleThemeSelection() {
    if (!state.themesDoc?.themes) return;
    const focused = state.themeById[state.focusedParentId];
    const active = state.themeById[state.activeTheme];
    const focusGone = !!(focused && themeMetricInYears(focused) <= 0);
    const activeGone = !!(active && themeMetricInYears(active) <= 0);
    if (!focusGone && !activeGone) return;
    state.focusedParentId = focusGone ? "" : state.focusedParentId;
    if (activeGone || (focusGone && state.chartPeriod.theme)) {
      state.chartPeriod.theme = "";
      state.activeTheme = "";
      state.focusedParentId = "";
      const themeSel = $("#periodTheme");
      if (themeSel) themeSel.value = "";
      invalidateChartStats();
      updatePeriodSummary();
    }
  }

  function refreshThemeViews() {
    pruneInvisibleThemeSelection();
    renderThemeChart();
    renderThemeYearChart();
    renderThemePodcastCharts();
    renderThemeDetail(state.activeTheme || state.focusedParentId || "");
  }

  function selectedTheme() {
    return (
      state.themeById[state.activeTheme] ||
      state.themeById[state.chartPeriod.theme] ||
      state.themeById[state.focusedParentId] ||
      null
    );
  }

  function episodeMatchesThemeId(thIds, themeId) {
    if (!themeId) return false;
    return (thIds || []).includes(themeId);
  }

  function episodesForTheme(themeId) {
    if (!themeId || !state.episodes?.length) return [];
    const out = [];
    // Sticky filters (incl. search) apply; theme comes from the selected chip/dropdown.
    const idxs = matchedEpisodeIndexes({ theme: "" });
    for (const i of idxs) {
      if (!episodeHasTheme(i, themeId)) continue;
      const e = state.episodes[i];
      const th = themeIdsForIndex(i);
      out.push({
        ...e,
        _i: i,
        _th: th,
        _country: state._epCountry ? state._epCountry[i] : countryForEpisode(e),
      });
    }
    return out;
  }

  function podcastsForTheme(themeId) {
    if (!themeId || !state.episodes?.length) return [];
    const byPod = new Map();
    const idxs = matchedEpisodeIndexes({ theme: "" });
    for (const i of idxs) {
      if (!episodeHasTheme(i, themeId)) continue;
      const e = state.episodes[i];
      const name = e.p || "Unknown";
      const cur = byPod.get(name) || { name, count: 0, hours: 0 };
      cur.count += 1;
      cur.hours += themeHoursForIndex(i, themeId);
      byPod.set(name, cur);
    }
    return [...byPod.values()].map((p) => ({
      ...p,
      hours: Math.round(p.hours * 10) / 10,
    }));
  }

  function jumpToThemePodcast(podcastName) {
    if (!podcastName) return;
    // Keep the active theme filter; narrow to this show, then jump to the
    // episode list (Explore) so theme ∩ show matches are visible.
    patchChartPeriod({ podcast: podcastName });
    goToSection("explorePanel");
  }

  function syncThemeMatchToggle() {
    $$("[data-theme-match]").forEach((btn) => {
      btn.setAttribute(
        "aria-pressed",
        btn.dataset.themeMatch === state.themeMatchView ? "true" : "false"
      );
    });
    const podHost = $("#themeMatchPodcasts");
    const epHost = $("#themeMatchEpisodes");
    if (podHost) podHost.hidden = state.themeMatchView !== "podcasts";
    if (epHost) epHost.hidden = state.themeMatchView !== "episodes";
  }

  function applyThemeMatchView(view) {
    const next = view === "episodes" ? "episodes" : "podcasts";
    if (state.themeMatchView === next) return;
    state.themeMatchView = next;
    state.themeMatchPage = 0;
    renderThemeMatchPanel();
  }

  function episodeCardHtml(e) {
    const note = noteTextForIndex(e._i);
    const noteMeta = state.notes?.[String(e._i)];
    const noteSrc = noteMeta?.src;
    const noteFull = noteMeta?.full || (noteMeta?.chars || 0) > 900;
    const noteLabel =
      noteSrc === "stt"
        ? noteFull
          ? "full STT"
          : "STT"
        : noteSrc === "transcript"
          ? noteFull
            ? "full transcript"
            : "transcript"
          : noteSrc === "show-notes"
            ? "show notes"
            : noteSrc;
    const themeTags = displayThemeTags(e._th || [])
      .map((id) => {
        const name = state.themeById[id]?.name || id;
        return `<button type="button" class="tag ok" data-theme-jump="${escapeHtml(id)}">${escapeHtml(name)}</button>`;
      })
      .join("");
    const snippet =
      note &&
      (String(state.chartPeriod.q || "").trim()
        ? note
        : note.length > 280
          ? note.slice(0, 280) + "…"
          : note);
    const country = e._country || countryForEpisode(e);
    return `
      <article class="ep">
        <div class="ep-show">${escapeHtml(e.p || "Podcast")}${e.f ? ` · ${escapeHtml(e.f)}` : ""}</div>
        <h3>${escapeHtml(e.e || "(untitled)")}</h3>
        <div class="ep-meta">
          <span>${escapeHtml(formatUiDate(e.d || e.t || ""))}</span>
          ${e.dur ? `<span>${escapeHtml(e.dur)}</span>` : ""}
          ${country && country !== "Unknown" ? `<button type="button" class="tag" data-country-jump="${escapeHtml(country)}">${escapeHtml(country)}</button>` : ""}
          ${e.st ? `<span class="tag ${e.st === "Played" ? "ok" : e.st === "In progress" ? "warn" : ""}">${escapeHtml(e.st)}</span>` : ""}
          ${e.prog !== "" && e.prog != null ? `<span>${escapeHtml(e.prog)}%</span>` : ""}
          ${e.star ? `<span class="tag ok">Starred</span>` : ""}
          ${noteLabel ? `<span class="tag ${noteFull ? "ok" : ""}">${escapeHtml(noteLabel)}</span>` : ""}
        </div>
        ${themeTags ? `<div class="ep-themes">${themeTags}</div>` : ""}
        ${snippet ? `<div class="ep-note">${escapeHtml(snippet)}</div>` : ""}
      </article>`;
  }

  function wireEpisodeCardJumps(rootSel, { jumpExplore = false } = {}) {
    const root = $(rootSel);
    if (!root) return;
    $$("[data-theme-jump]", root).forEach((btn) => {
      btn.addEventListener("click", () => selectTheme(btn.dataset.themeJump, jumpExplore));
    });
    $$("[data-country-jump]", root).forEach((btn) => {
      btn.addEventListener("click", () => {
        const c = btn.dataset.countryJump;
        if (!c) return;
        patchChartPeriod({ country: c });
      });
    });
  }

  function setThemeMatchPanelVisible(visible) {
    const panel = $("#themeMatchPanel");
    if (panel) panel.hidden = !visible;
  }

  function renderThemeMatchPanel() {
    const theme = selectedTheme();
    const title = $("#themeMatchTitle");
    const note = $("#themeMatchNote");
    const scope = chartPeriodLabel({ omitTheme: true });
    const hours = metricIsHours();
    syncThemeMatchToggle();

    const themeId = theme?.id || "";
    if (themeId !== state._themeMatchThemeId) {
      state._themeMatchThemeId = themeId;
      state.themeMatchPage = 0;
      state.barReveal.themePod = null;
    }

    // Hide until a theme is selected and there are matching shows/episodes.
    if (!theme) {
      setThemeMatchPanelVisible(false);
      return;
    }

    if (state.themeMatchView === "episodes") {
      const rows = episodesForTheme(theme.id);
      if (!rows.length) {
        setThemeMatchPanelVisible(false);
        return;
      }
      setThemeMatchPanelVisible(true);
      const totalPages = Math.max(1, Math.ceil(rows.length / state.themeMatchPageSize));
      if (state.themeMatchPage >= totalPages) state.themeMatchPage = totalPages - 1;
      if (state.themeMatchPage < 0) state.themeMatchPage = 0;
      const start = state.themeMatchPage * state.themeMatchPageSize;
      const slice = rows.slice(start, start + state.themeMatchPageSize);
      if (title) title.textContent = `${theme.name} · episodes`;
      if (note) {
        note.textContent = `${fmt(rows.length)} episodes tagged ${theme.name} in ${scope}.`;
      }
      const list = $("#themeEpisodeList");
      if (list) list.innerHTML = slice.map(episodeCardHtml).join("");
      if ($("#themePageInfo")) {
        $("#themePageInfo").textContent = `Page ${state.themeMatchPage + 1} / ${totalPages}`;
      }
      if ($("#themePrevPage")) $("#themePrevPage").disabled = state.themeMatchPage <= 0;
      if ($("#themeNextPage")) {
        $("#themeNextPage").disabled = state.themeMatchPage >= totalPages - 1;
      }
      wireEpisodeCardJumps("#themeEpisodeList");
      return;
    }

    const items = podcastsForTheme(theme.id)
      .slice()
      .sort((a, b) =>
        hours
          ? b.hours - a.hours || a.name.localeCompare(b.name)
          : b.count - a.count || a.name.localeCompare(b.name)
      );
    if (!items.length) {
      setThemeMatchPanelVisible(false);
      return;
    }
    setThemeMatchPanelVisible(true);
    const top = items[0];
    if (title) {
      title.textContent = hours
        ? `${theme.name} · podcasts by hours`
        : `${theme.name} · podcasts by episodes`;
    }
    if (note) {
      note.textContent = `${fmt(items.length)} shows in ${scope}. Top: ${top.name} (${
        hours ? `${fmtHours(top.hours)}h` : fmt(top.count)
      }). Tap a bar to filter Explore.`;
    }
    renderExpandableHBar({
      key: "themePod",
      canvasSel: "#themePodChart",
      boxSel: "#themePodBox",
      moreSel: "#themePodMore",
      items,
      labelOf: (d) => d.name,
      valueOf: (d) => (hours ? d.hours : d.count),
      // Match the focused theme highlight on the Themes chart.
      color: themeFocusColor(),
      onClick: (d) => jumpToThemePodcast(d?.name),
    });
  }

  /** @deprecated name kept as alias while call sites migrate */
  function renderThemePodcastCharts() {
    renderThemeMatchPanel();
  }

  function displayThemeTags(ids) {
    // Flat taxonomy: show every assigned theme id that still exists in the catalog.
    return (ids || []).filter((id) => state.themeById[id]);
  }

  function themeIdsForIndex(i) {
    return (state.episodeThemes && state.episodeThemes[i]) || [];
  }

  function themeWeightForIndex(i, themeId) {
    if (i == null || !themeId) return 0;
    const wmap = state.episodeThemeWeights && state.episodeThemeWeights[i];
    if (wmap && typeof wmap === "object" && wmap[themeId] != null) {
      const w = Number(wmap[themeId]);
      return Number.isFinite(w) && w > 0 ? w : 0;
    }
    // Legacy equal split when weights file missing
    const ids = themeIdsForIndex(i);
    if (!ids.includes(themeId)) return 0;
    return ids.length ? 1 / ids.length : 0;
  }

  function themeHoursForIndex(i, themeId) {
    const h = episodeHours(state.episodes[i], i);
    return h * themeWeightForIndex(i, themeId);
  }


  function noteTextForIndex(i) {
    const n = state.notes && state.notes[String(i)];
    return n?.text || "";
  }

  function filteredEpisodes() {
    const idxs = matchedEpisodeIndexes();
    const out = new Array(idxs.length);
    for (let n = 0; n < idxs.length; n++) {
      const i = idxs[n];
      const e = state.episodes[i];
      out[n] = {
        ...e,
        _i: i,
        _th: themeIdsForIndex(i),
        _country: state._epCountry ? state._epCountry[i] : countryForEpisode(e),
      };
    }
    return out;
  }

  function renderEpisodeList() {
    const idxs = matchedEpisodeIndexes();
    const total = idxs.length;
    const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
    if (state.page >= totalPages) state.page = totalPages - 1;
    if (state.page < 0) state.page = 0;
    const start = state.page * state.pageSize;
    const end = Math.min(total, start + state.pageSize);
    const slice = [];
    for (let n = start; n < end; n++) {
      const i = idxs[n];
      const e = state.episodes[i];
      slice.push({
        ...e,
        _i: i,
        _th: themeIdsForIndex(i),
        _country: state._epCountry ? state._epCountry[i] : countryForEpisode(e),
      });
    }

    $("#listMeta").textContent = `${fmt(total)} matching episodes`;
    $("#episodeList").innerHTML =
      slice.map(episodeCardHtml).join("") ||
      `<div class="empty">No episodes match these filters.</div>`;

    $("#pageInfo").textContent = `Page ${state.page + 1} / ${totalPages}`;
    $("#prevPage").disabled = state.page <= 0;
    $("#nextPage").disabled = state.page >= totalPages - 1 || !total;

    wireEpisodeCardJumps("#episodeList", { jumpExplore: true });

    // Insights: prefer chart stats when available (same filter scope).
    const hours = metricIsHours();
    let top = [];
    const stats = state._chartStatsCache?.[`${chartPeriodKey()}|theme:on|g:${themeTrendGrain()}`];
    if (stats) {
      const src = hours ? stats.byPodcastHours : stats.byPodcastCount;
      top = Object.entries(src)
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 5);
    } else {
      const byPod = Object.create(null);
      for (const i of idxs) {
        const e = state.episodes[i];
        const key = e.p || "Unknown";
        byPod[key] = (byPod[key] || 0) + (hours ? episodeHours(e, i) : 1);
      }
      top = Object.entries(byPod).sort((a, b) => b[1] - a[1]).slice(0, 5);
    }
    $("#filterInsights").innerHTML = top.length
      ? `<strong>In this view:</strong> ` +
        top
          .map(([n, c]) => `${escapeHtml(n)} (${fmtMetric(c)}${hours ? "h" : ""})`)
          .join(" · ")
      : "";
  }

  function themeChartItems() {
    return themesPresentInFilter(flatThemes())
      .slice()
      .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a));
  }

  /** Pin the focused theme to the top so it stays visible while highlighted. */
  function themeChartItemsPinned(focusId) {
    const items = themeChartItems();
    if (!focusId) return items;
    const focused = items.find((t) => t.id === focusId);
    if (!focused) return items;
    return [focused, ...items.filter((t) => t.id !== focusId)];
  }

  function leaveThemeDrill() {
    state.focusedParentId = "";
    state.barReveal.theme = BAR_PAGE;
    selectTheme("", false);
  }

  function renderThemeChart() {
    if (!state.themesDoc?.themes) return;
    const active = state.themeById[state.activeTheme];
    const focusId = active?.id || "";
    const items = themeChartItemsPinned(focusId);
    const title = $("#themeChartTitle");
    const back = $("#themeChartBack");
    const periodLabel = chartPeriodActive()
      ? chartPeriodLabel({ omitTheme: !!active })
      : "";
    const yearSuffix = periodLabel && periodLabel !== "All time" ? ` · ${periodLabel}` : "";
    if (title) {
      title.textContent = active
        ? `${active.name}${yearSuffix}`
        : `Themes${yearSuffix}`;
    }
    if (back) {
      const label = back.querySelector(".theme-nav-back-label");
      back.hidden = !active;
      if (label) label.textContent = "Themes";
      back.setAttribute("aria-label", "Clear theme selection");
      back.onclick = active ? () => leaveThemeDrill() : null;
    }
    const baseColor = palette().teal;
    const focusColor = themeFocusColor();
    renderExpandableHBar({
      key: "theme",
      canvasSel: "#themeChart",
      boxSel: "#themeChartBox",
      moreSel: "#themeChartMore",
      items,
      labelOf: (d) => d.name,
      valueOf: (d) => themeMetricInYears(d),
      preserveOrder: !!focusId,
      colorOf: (d) => (d.id === focusId ? focusColor : baseColor),
      onClick: (d) => {
        if (!d?.id) return;
        selectTheme(d.id, false);
      },
    });
  }

  function themeYearSeriesThemes() {
    const active = state.themeById[state.activeTheme];
    if (active && themeMetricInYears(active) > 0) return [active];
    return themesPresentInFilter(flatThemes())
      .slice()
      .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a))
      .slice(0, 6);
  }

  function themeTrendGrain() {
    return periodAxisKeys().grain === "day"
      ? "day"
      : dateRangeActive()
        ? "month"
        : "year";
  }

  function themeTrendBuckets() {
    const grain = themeTrendGrain();
    if (grain === "day") {
      const { from, to } = effectiveDateRange();
      return enumerateDayKeysInclusive(from, to);
    }
    if (grain === "month") {
      const { from, to } = effectiveDateRange();
      return enumerateMonthKeys(from.slice(0, 7), to.slice(0, 7));
    }
    const years = historyYearKeys();
    if (years.length) return years;
    const stats = ensureChartStats({ ignoreTheme: true });
    return Object.keys(stats.byYearCount || {}).sort((a, b) => Number(a) - Number(b));
  }

  function themeTrendValue(t, bucket) {
    const stats = ensureChartStats({ ignoreTheme: true });
    const grain = themeTrendGrain();
    const hours = metricIsHours();
    if (grain === "day") {
      return Number((hours ? stats.byThemeDateHours : stats.byThemeDateCount)[t.id]?.[bucket] || 0);
    }
    if (grain === "month") {
      return Number((hours ? stats.byThemeMonthHours : stats.byThemeMonthCount)[t.id]?.[bucket] || 0);
    }
    return Number((hours ? stats.byThemeYearHours : stats.byThemeYearCount)[t.id]?.[bucket] || 0);
  }

  function themeTrendLabel(bucket) {
    const grain = themeTrendGrain();
    if (grain === "day") return formatDateKey(bucket);
    if (grain === "month") return formatMonthKey(bucket);
    return String(bucket);
  }

  function renderThemeYearChart() {
    if (!state.themesDoc?.themes) return;
    const canvas = $("#themeYearChart");
    if (!canvas) return;
    const buckets = themeTrendBuckets();
    const series = themeYearSeriesThemes();
    const title = $("#themeYearChartTitle");
    const note = $("#themeYearChartNote");
    const focusName =
      state.themeById[state.activeTheme]?.name ||
      state.themeById[state.focusedParentId]?.name;
    const hours = metricIsHours();
    const grain = themeTrendGrain();
    const grainWord = grain === "day" ? "days" : grain === "month" ? "months" : "years";
    if (title) {
      title.textContent = focusName
        ? `${focusName} over ${grainWord}`
        : `Themes over ${grainWord}`;
    }
    if (note) {
      const scope = chartPeriodActive() ? ` in ${chartPeriodLabel()}` : "";
      note.textContent = focusName
        ? `${hours ? "Hours" : "Episode counts"} for ${focusName}${scope}.`
        : hours
          ? `Top themes by within-episode hours across ${grainWord} — scoped by the filter bar above.`
          : `Top themes across ${grainWord} — scoped by the filter bar above.`;
    }
    destroyChart("themeYear");
    state.charts.themeYear = new Chart(canvas, {
      type: "line",
      data: {
        labels: buckets.map(themeTrendLabel),
        datasets: series.map((t, i) => ({
          label: t.name,
          data: buckets.map((b) => themeTrendValue(t, b)),
          borderColor: categorical()[i % categorical().length],
          backgroundColor: "transparent",
          tension: 0.28,
          pointRadius: 3,
          pointHoverRadius: 5,
          borderWidth: 2.4,
        })),
      },
      options: baseChartOptions({
        plugins: {
          legend: {
            display: series.length > 1,
            position: "bottom",
            labels: { boxWidth: 12, boxHeight: 12, padding: 14 },
          },
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${fmtMetric(ctx.parsed.y)}`,
            },
          },
        },
      }),
    });
  }

  function renderThemeDetail(themeId) {
    const t = state.themeById[themeId] || state.themeById[state.activeTheme];
    const title = $("#themeDetailTitle");
    const blurb = $("#themeDetailBlurb");
    const samples = $("#themeSamples");
    const showsWrap = $("#themeShowsWrap");
    const btn = $("#filterByTheme");
    if (!t) {
      title.textContent = "Pick a theme";
      blurb.textContent =
        "Tap a theme to see which shows cover it. Local themes are specific (e.g. Brazilian elections); the sticky filter bar scopes counts.";
      if (samples) samples.innerHTML = "";
      if (showsWrap) showsWrap.hidden = true;
      destroyChart("themeShows");
      state.barReveal.themeShows = null;
      btn.hidden = true;
      return;
    }
    const n = themeMetricInYears(t);
    const periodSuffix = chartPeriodActive() ? ` in ${chartPeriodLabel()}` : "";
    const hours = metricIsHours();
    const unit = hours ? "hours" : "episodes";
    const ev = t.evidence || {};
    const evBits = [
      ev.transcript ? `${fmt(ev.transcript)} transcript-backed` : "",
      ev.notes ? `${fmt(ev.notes)} notes-backed` : "",
      ev.title ? `${fmt(ev.title)} title-only` : "",
    ].filter(Boolean);
    title.textContent = t.name;
    const items = podcastsForTheme(t.id)
      .slice()
      .sort((a, b) =>
        hours
          ? b.hours - a.hours || a.name.localeCompare(b.name)
          : b.count - a.count || a.name.localeCompare(b.name)
      );
    if (t.id !== state._themeShowsThemeId) {
      state._themeShowsThemeId = t.id;
      state.barReveal.themeShows = null;
    }
    if (!items.length) {
      blurb.textContent = `${t.blurb} · ${fmtMetric(n)} ${unit}${periodSuffix}.${
        evBits.length ? ` Evidence: ${evBits.join(", ")}.` : ""
      } No matching shows under the current filters.`;
      if (samples) {
        samples.innerHTML = `<div class="empty">No shows match this theme${periodSuffix || ""}.</div>`;
      }
      if (showsWrap) showsWrap.hidden = true;
      destroyChart("themeShows");
      btn.hidden = false;
      btn.onclick = () => selectTheme(t.id, true);
      return;
    }
    const top = items[0];
    blurb.textContent = `${t.blurb} · ${fmtMetric(n)} ${unit}${periodSuffix} · ${fmt(items.length)} shows (top: ${top.name}, ${
      hours ? `${fmtHours(top.hours)}h` : fmt(top.count)
    }).${evBits.length ? ` Evidence: ${evBits.join(", ")}.` : ""} Tap a show to open matching episodes.`;
    if (samples) samples.innerHTML = "";
    if (showsWrap) showsWrap.hidden = false;
    renderExpandableHBar({
      key: "themeShows",
      canvasSel: "#themeShowsChart",
      boxSel: "#themeShowsBox",
      moreSel: "#themeShowsMore",
      items,
      labelOf: (d) => d.name,
      valueOf: (d) => (hours ? d.hours : d.count),
      color: themeFocusColor(),
      onClick: (d) => jumpToThemePodcast(d?.name),
    });
    btn.hidden = false;
    btn.onclick = () => selectTheme(t.id, true);
  }

  function focusParentTheme(parentId) {
    // Flat taxonomy: same as selecting a theme.
    selectTheme(parentId || "", false);
  }

  function selectTheme(themeId, jumpExplore) {
    const patch = { theme: themeId || "" };
    if (themeId) patch.q = "";
    patchChartPeriod(patch);
    if (jumpExplore) {
      goToSection("explorePanel");
    }
  }

  function wire() {
    $("#prevPage").addEventListener("click", () => {
      state.page -= 1;
      renderEpisodeList();
      $("#episodeList").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $("#nextPage").addEventListener("click", () => {
      state.page += 1;
      renderEpisodeList();
      $("#episodeList").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $$("[data-theme-match]").forEach((btn) => {
      btn.addEventListener("click", () => applyThemeMatchView(btn.dataset.themeMatch));
    });
    $("#themePrevPage")?.addEventListener("click", () => {
      state.themeMatchPage -= 1;
      renderThemeMatchPanel();
      $("#themeEpisodeList")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    $("#themeNextPage")?.addEventListener("click", () => {
      state.themeMatchPage += 1;
      renderThemeMatchPanel();
      $("#themeEpisodeList")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });

    // Desktop: scroll-spy. Mobile: bottom tabs swap panels (no long scroll).
    const enableScrollSpy = () => {
      if (!("IntersectionObserver" in window) || isTabMode()) return;
      sectionScrollSpy?.disconnect?.();
      const seen = new Map();
      sectionScrollSpy = new IntersectionObserver(
        (entries) => {
          if (isTabMode()) return;
          for (const entry of entries) {
            seen.set(entry.target.id, entry.intersectionRatio);
          }
          let best = JUMP_TARGETS[0];
          let bestRatio = -1;
          for (const id of JUMP_TARGETS) {
            const r = seen.get(id) || 0;
            if (r > bestRatio) {
              bestRatio = r;
              best = id;
            }
          }
          if (bestRatio > 0) {
            activeTabId = best;
            setActiveJump(best);
          }
        },
        { rootMargin: "-28% 0px -55% 0px", threshold: [0, 0.1, 0.25, 0.5, 0.75] }
      );
      JUMP_TARGETS.forEach((id) => {
        const el = document.getElementById(id);
        if (el) sectionScrollSpy.observe(el);
      });
    };

    $$("[data-jump]").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        const id = a.getAttribute("data-jump");
        goToSection(id);
        try {
          history.replaceState(null, "", `#${id}`);
        } catch (_) {}
      });
    });

    const hashTab = () => {
      const raw = (location.hash || "").replace(/^#/, "");
      return JUMP_TARGETS.includes(raw) ? raw : "trends";
    };
    activeTabId = hashTab();
    syncTabMode();
    enableScrollSpy();
    TAB_MQ.addEventListener("change", () => {
      syncTabMode();
      enableScrollSpy();
    });

    $("#themeToggle")?.addEventListener("click", () => {
      applyTheme(isDark() ? "light" : "dark");
      rerenderCharts();
    });
    $$("[data-metric]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.metric === state.metric) return;
        applyMetric(btn.dataset.metric);
      });
    });
    $$("[data-date-preset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-date-preset") || "all";
        const bounds = datePresetBounds(key);
        patchChartPeriod({
          from: bounds.from,
          to: bounds.to,
          preset: bounds.preset,
        });
      });
    });
    const onDateInput = () => {
      const from = normalizeISODate($("#periodFrom")?.value);
      const to = normalizeISODate($("#periodTo")?.value);
      patchChartPeriod({
        from,
        to,
        preset: inferDatePreset(from, to),
      });
    };
    $("#periodFrom")?.addEventListener("change", onDateInput);
    $("#periodTo")?.addEventListener("change", onDateInput);
    $("#periodCountry")?.addEventListener("change", (e) => {
      patchChartPeriod({ country: e.target.value });
    });
    $("#periodPodcast")?.addEventListener("change", (e) => {
      patchChartPeriod({ podcast: e.target.value });
    });
    $("#periodTheme")?.addEventListener("change", (e) => {
      selectTheme(e.target.value || "", false);
    });
    $("#periodStatus")?.addEventListener("change", (e) => {
      patchChartPeriod({ status: e.target.value });
    });
    let qTimer;
    $("#periodQ")?.addEventListener("input", (e) => {
      clearTimeout(qTimer);
      qTimer = setTimeout(() => {
        state.themeMatchPage = 0;
        patchChartPeriod({ q: e.target.value });
      }, 260);
    });

    upgradeSearchableSelect($("#periodPodcast"), { emptyLabel: "All shows", title: "Shows" });
    upgradeSearchableSelect($("#periodCountry"), {
      emptyLabel: "All countries",
      title: "Country",
    });
    upgradeSearchableSelect($("#periodTheme"), { emptyLabel: "All themes", title: "Theme" });
    refreshSearchableSelects();

    const clearAllFilters = () => {
      applyChartPeriod({
        from: "",
        to: "",
        preset: "all",
        country: "",
        podcast: "",
        theme: "",
        status: "",
        q: "",
      });
      if ($("#periodQ")) $("#periodQ").value = "";
      refreshSearchableSelects();
      syncFilterBadge();
    };

    $("#filterSheetToggle")?.addEventListener("click", () => {
      const open = isCompactFilterUi()
        ? !document.body.classList.contains("filter-sheet-open")
        : !document.body.classList.contains("filters-expanded");
      setFilterSheetOpen(open);
    });
    $("#filterSheetDone")?.addEventListener("click", () => setFilterSheetOpen(false));
    $("#filterSheetBackdrop")?.addEventListener("click", () => setFilterSheetOpen(false));
    $("#filterSheetClear")?.addEventListener("click", () => {
      clearAllFilters();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (document.body.classList.contains("combo-picker-open")) {
        e.preventDefault();
        closeComboPicker(false);
        return;
      }
      if (
        document.body.classList.contains("filter-sheet-open") ||
        document.body.classList.contains("filters-expanded")
      ) {
        setFilterSheetOpen(false);
      }
    });
    document.addEventListener("pointerdown", (e) => {
      if (!document.body.classList.contains("filters-expanded")) return;
      if (isCompactFilterUi()) return;
      const bar = $("#periodBar");
      const t = e.target;
      if (bar && t instanceof Node && bar.contains(t)) return;
      setFilterSheetOpen(false);
    });
    const onViewport = () => {
      syncVisualViewportVars();
      guardHorizontalOverflow();
    };
    syncVisualViewportVars();
    guardHorizontalOverflow();
    window.visualViewport?.addEventListener("resize", onViewport);
    window.visualViewport?.addEventListener("scroll", onViewport);
    window.matchMedia("(max-width: 860px)").addEventListener("change", () => {
      closeComboPicker(false);
      document.body.classList.remove("filters-expanded");
      setFilterSheetOpen(false);
      placeFilterToggle();
      placeFilterPanel(false);
      layoutDesktopFilterOverflow();
      guardHorizontalOverflow();
    });
    let filterLayoutTimer = 0;
    window.addEventListener("resize", () => {
      clearTimeout(filterLayoutTimer);
      filterLayoutTimer = window.setTimeout(() => {
        layoutDesktopFilterOverflow();
        guardHorizontalOverflow();
      }, 80);
    });

    $("#periodClear")?.addEventListener("click", () => clearAllFilters());
    $("#hardRefresh")?.addEventListener("click", () => {
      hardRefresh();
    });
  }

  async function loadAll() {
    if (window.__LISTENING_DATA__) {
      const d = window.__LISTENING_DATA__;
      return [
        d.aggregates,
        d.episodes,
        d.podcasts,
        d.themes || null,
        d.episodeThemes || null,
        d.episodeThemeWeights || null,
        d.notes || null,
        d.countries || null,
      ];
    }
    return Promise.all([
      loadJSON("tables/aggregates.json"),
      loadJSON("tables/episodes.json"),
      loadJSON("tables/podcasts.json"),
      loadJSON("tables/themes.json").catch(() => null),
      loadJSON("tables/episode-themes.json").catch(() => null),
      loadJSON("tables/episode-theme-weights.json").catch(() => null),
      loadJSON("tables/notes.json").catch(() => null),
      loadJSON("tables/podcast-countries.json").catch(() => null),
    ]);
  }

  async function init() {
    syncThemeToggle();
    state.metric = readStoredMetric();
    syncMetricToggle();
    updateMetricLabels();
    // Enter mobile tab panels before charts paint so inactive canvases aren't laid out in a long scroll.
    try {
      const raw = (location.hash || "").replace(/^#/, "");
      if (JUMP_TARGETS.includes(raw)) activeTabId = raw;
    } catch (_) {}
    syncTabMode();
    $("#bootStatus").textContent = "Loading listening history…";
    try {
      const [agg, episodes, podcasts, themesDoc, episodeThemes, episodeThemeWeights, notes, countriesDoc] =
        await loadAll();
      state.agg = agg;
      state.episodes = episodes;
      state.podcasts = podcasts;
      state.themesDoc = themesDoc;
      state.episodeThemes = episodeThemes;
      state.episodeThemeWeights = episodeThemeWeights;
      state.notes = notes || {};
      state.countriesDoc = countriesDoc || { byPodcast: {}, byAuthor: {} };
      state._periodIndex = null;
      invalidateChartStats();
      const flat = themesDoc?.flat || [];
      const parents = themesDoc?.themes || [];
      const byId = {};
      for (const t of parents) {
        byId[t.id] = t;
        for (const c of t.children || []) byId[c.id] = c;
      }
      for (const t of flat) if (!byId[t.id]) byId[t.id] = t;
      state.themeById = byId;
      $("#bootStatus").textContent = "Indexing listening history…";
      prepareEpisodeIndex();

      renderHeroStats();
      populateFilters();
      syncPeriodControls();
      updatePeriodSummary();
      updateMetricLabels();
      renderTrendChart();
      renderCumulativeChart();
      renderYearChart();
      renderYoYChart();
      renderTopPodcastsChart();
      renderWeekdayHourCharts();
      renderFolderStatusCharts();
      renderCountryChart();
      renderDurationChart();
      renderHeatmap();
      renderThemeChart();
      renderThemeYearChart();
      renderThemePodcastCharts();
      renderThemeDetail("");
      renderEpisodeList();
      wire();
      placeFilterToggle();
      layoutDesktopFilterOverflow();
      document.body.classList.add("ready");
      $("#bootStatus").textContent = "";
      showTab(activeTabId, { scrollTop: false });
      requestAnimationFrame(() => layoutDesktopFilterOverflow());
      // Warm search haystacks in idle time so the first typed query stays snappy.
      const warmSearch = () => {
        try {
          ensureSearchIndex();
        } catch (_) {}
      };
      if (typeof requestIdleCallback === "function") {
        requestIdleCallback(warmSearch, { timeout: 2500 });
      } else {
        setTimeout(warmSearch, 600);
      }
      try {
        if (new URLSearchParams(location.search).get("filters") === "open") {
          setFilterSheetOpen(true);
        }
      } catch (_) {}
    } catch (err) {
      $("#bootStatus").textContent = `Failed to load: ${err.message}`;
      console.error(err);
    }
  }

  init();
})();
