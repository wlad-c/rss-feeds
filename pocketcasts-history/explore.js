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
    notes: null,
    themeById: {},
    activeTheme: "",
    focusedParentId: "",
    themeMatchView: "podcasts", // "podcasts" | "episodes"
    themeMatchPage: 0,
    themeMatchPageSize: 25,
    _themeMatchThemeId: "",
    metric: "episodes", // "episodes" | "hours"
    chartPeriod: {
      year: "",
      month: "",
      day: "",
      country: "",
      podcast: "",
      theme: "",
      status: "",
      q: "",
    },
    charts: {},
    barReveal: {},
    tableReveal: { top: 12 },
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

  function chartPeriodActive() {
    const { year, month, day, country, podcast, theme, status, q } = state.chartPeriod;
    return !!(year || month || day || country || podcast || theme || status || String(q || "").trim());
  }

  function chartPeriodKey() {
    const { year, month, day, country, podcast, theme, status, q } = state.chartPeriod;
    return [
      year || "all",
      month || "all",
      day || "all",
      country || "all",
      podcast || "all",
      theme || "all",
      status || "all",
      String(q || "").trim().toLowerCase() || "all",
    ].join("|");
  }

  function chartPeriodLabel(opts = {}) {
    const { year, month, day, country, podcast, theme, status, q } = state.chartPeriod;
    const bits = [];
    if (year) {
      if (!month) bits.push(String(year));
      else if (day) bits.push(formatDateKey(`${year}-${month}-${String(day).padStart(2, "0")}`));
      else bits.push(formatMonthKey(`${year}-${month}`));
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
    const year = overrides && Object.prototype.hasOwnProperty.call(overrides, "year")
      ? overrides.year
      : base.year;
    const month = overrides && Object.prototype.hasOwnProperty.call(overrides, "month")
      ? overrides.month
      : base.month;
    const day = overrides && Object.prototype.hasOwnProperty.call(overrides, "day")
      ? overrides.day
      : base.day;
    const country = overrides && Object.prototype.hasOwnProperty.call(overrides, "country")
      ? overrides.country
      : base.country;
    const podcast = overrides && Object.prototype.hasOwnProperty.call(overrides, "podcast")
      ? overrides.podcast
      : base.podcast;
    const theme = overrides && Object.prototype.hasOwnProperty.call(overrides, "theme")
      ? overrides.theme
      : base.theme;
    const status = overrides && Object.prototype.hasOwnProperty.call(overrides, "status")
      ? overrides.status
      : base.status;
    const q = overrides && Object.prototype.hasOwnProperty.call(overrides, "q")
      ? overrides.q
      : base.q;
    const qq = String(q || "").trim().toLowerCase();
    if (!year && !month && !day && !country && !podcast && !theme && !status && !qq) return true;
    const d = String(e.d || "");
    if (year && String(e.y) !== String(year)) return false;
    if (month && d.slice(5, 7) !== month) return false;
    if (day && d.slice(8, 10) !== day) return false;
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
    renderTopTable();
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
    const t = state.themeById[themeId];
    state.activeTheme = themeId;
    if (!themeId) {
      state.focusedParentId = "";
      return;
    }
    if (t?.parentId) state.focusedParentId = t.parentId;
    else state.focusedParentId = themeId;
  }

  function ensurePeriodIndex() {
    if (state._periodIndex) return state._periodIndex;
    const years = new Set();
    const monthsByYear = Object.create(null);
    const daysByYm = Object.create(null);
    for (const e of state.episodes || []) {
      const d = String(e.d || "");
      const y = e.y != null && e.y !== "" ? String(e.y) : d.slice(0, 4);
      if (!y || y.length !== 4) continue;
      years.add(y);
      const m = d.slice(5, 7);
      if (!m) continue;
      if (!monthsByYear[y]) monthsByYear[y] = new Set();
      monthsByYear[y].add(m);
      const day = d.slice(8, 10);
      if (!day) continue;
      const ym = `${y}-${m}`;
      if (!daysByYm[ym]) daysByYm[ym] = new Set();
      daysByYm[ym].add(day);
    }
    state._periodIndex = {
      years: [...years].sort((a, b) => Number(b) - Number(a)),
      monthsByYear,
      daysByYm,
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
    const year = next.year ? String(next.year) : "";
    const month = year && next.month ? String(next.month).padStart(2, "0") : "";
    const day = year && month && next.day ? String(next.day).padStart(2, "0") : "";
    const pick = (key) =>
      Object.prototype.hasOwnProperty.call(next, key)
        ? String(next[key] || "")
        : String(state.chartPeriod[key] || "");
    const country = pick("country");
    const podcast = pick("podcast");
    const theme = pick("theme");
    const status = pick("status");
    const q = Object.prototype.hasOwnProperty.call(next, "q")
      ? String(next.q || "")
      : String(state.chartPeriod.q || "");
    state.chartPeriod = { year, month, day, country, podcast, theme, status, q };
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
    state.tableReveal.top = BAR_PAGE;
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
    const opts = ['<option value="">All themes</option>'];
    for (const p of state.themesDoc.themes) {
      const parentHit = themeMetricInYears(p) > 0 || p.id === selected;
      const kids = (p.children || []).filter(
        (c) => themeMetricInYears(c) > 0 || c.id === selected
      );
      if (!parentHit && !kids.length) continue;
      if (parentHit) {
        opts.push(`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`);
      }
      for (const c of kids) {
        opts.push(
          `<option value="${escapeHtml(c.id)}">↳ ${escapeHtml(c.name)}</option>`
        );
      }
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

  function syncPeriodControls({ skipThemes = false } = {}) {
    const yearSel = $("#periodYear");
    const monthSel = $("#periodMonth");
    const daySel = $("#periodDay");
    const countrySel = $("#periodCountry");
    const podcastSel = $("#periodPodcast");
    const statusSel = $("#periodStatus");
    const qInput = $("#periodQ");
    if (!yearSel || !monthSel || !daySel) return;
    const idx = ensurePeriodIndex();
    const { year, month, day, country, podcast, status, q } = state.chartPeriod;
    yearSel.innerHTML =
      `<option value="">All years</option>` +
      idx.years.map((y) => `<option value="${escapeHtml(y)}">${escapeHtml(y)}</option>`).join("");
    yearSel.value = year || "";

    const months = year ? [...(idx.monthsByYear[year] || [])].sort() : [];
    monthSel.disabled = !year;
    monthSel.innerHTML =
      `<option value="">All months</option>` +
      months
        .map((m) => `<option value="${m}">${escapeHtml(MONTH_NAME[m] || m)}</option>`)
        .join("");
    monthSel.value = month && months.includes(month) ? month : "";

    const ym = year && monthSel.value ? `${year}-${monthSel.value}` : "";
    const days = ym ? [...(idx.daysByYm[ym] || [])].sort() : [];
    daySel.disabled = !ym;
    daySel.innerHTML =
      `<option value="">All days</option>` +
      days.map((d) => `<option value="${d}">${Number(d)}</option>`).join("");
    daySel.value = day && days.includes(day) ? day : "";

    if (state.chartPeriod.month !== monthSel.value || state.chartPeriod.day !== daySel.value) {
      state.chartPeriod.month = monthSel.value || "";
      state.chartPeriod.day = daySel.value || "";
    }

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
    const height = vv ? vv.height : window.innerHeight;
    document.documentElement.style.setProperty("--vv-top", `${Math.round(top)}px`);
    document.documentElement.style.setProperty("--vv-height", `${Math.round(height)}px`);
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

  function closeComboPicker(restoreFocus) {
    const host = $("#comboPickerHost");
    if (!host || host.hidden) {
      comboPickerState = null;
      document.body.classList.remove("combo-picker-open");
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

    const selectedLabel = () => {
      const opt = select.options[select.selectedIndex];
      return opt ? opt.textContent : emptyLabel;
    };

    const paintClosed = () => {
      input.value = select.value ? selectedLabel() : "";
      input.placeholder = emptyLabel;
      highlight = -1;
    };

    const closeDesktop = () => {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      highlight = -1;
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
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
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
        if (!wrap.contains(document.activeElement)) closeDesktop();
      }, 140);
    });

    select._comboPaint = paintClosed;
    select._comboInput = input;
    select._comboOpenMobile = openMobile;
    paintClosed();
  }

  function activeFacetCount() {
    const p = state.chartPeriod;
    let n = 0;
    if (p.year) n += 1;
    if (p.month) n += 1;
    if (p.day) n += 1;
    if (p.country) n += 1;
    if (p.podcast) n += 1;
    if (p.theme) n += 1;
    if (p.status) n += 1;
    return n;
  }

  function syncFilterBadge() {
    const badge = $("#filterBadge");
    const toggle = $("#filterSheetToggle");
    const clearBtn = $("#periodClear");
    const n = activeFacetCount();
    if (badge) {
      if (n > 0) {
        badge.hidden = false;
        badge.textContent = String(n);
      } else {
        badge.hidden = true;
      }
    }
    toggle?.classList.toggle("has-filters", n > 0);
    if (clearBtn) clearBtn.hidden = n === 0 && !String(state.chartPeriod.q || "").trim();
  }

  function placeFilterPanel(inSheet) {
    const panel = $("#filterPanel");
    const sheetBody = $("#filterSheetBody");
    const periodBar = $("#periodBar");
    if (!panel || !sheetBody || !periodBar) return;
    if (inSheet) {
      if (panel.parentElement !== sheetBody) sheetBody.appendChild(panel);
    } else if (panel.parentElement !== periodBar) {
      periodBar.appendChild(panel);
    }
  }

  function setFilterSheetOpen(open) {
    const mobile = window.matchMedia("(max-width: 860px)").matches;
    const on = !!open && mobile;
    if (!on) closeComboPicker(false);
    document.body.classList.toggle("filter-sheet-open", on);
    const toggle = $("#filterSheetToggle");
    const backdrop = $("#filterSheetBackdrop");
    const sheet = $("#filterSheetPanel");
    if (toggle) toggle.setAttribute("aria-expanded", on ? "true" : "false");
    if (backdrop) backdrop.hidden = !on;
    if (sheet) sheet.hidden = !on;
    placeFilterPanel(on);
    if (on) {
      requestAnimationFrame(() => {
        $("#periodYear")?.focus({ preventScroll: true });
      });
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
    const grain = state.chartPeriod.day
      ? "day"
      : state.chartPeriod.month
        ? "day"
        : state.chartPeriod.year
          ? "month"
          : "month";
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
    if (state.chartPeriod.month) {
      setText("#yearChartTitle", "Episodes by day", "Hours by day");
    } else if (state.chartPeriod.year) {
      setText("#yearChartTitle", "Episodes by month", "Hours by month");
    } else {
      setText("#yearChartTitle", "Episodes by year", "Hours by year");
    }
    setText("#yoyChartNote", "Compare January–December volume across years.", "Compare January–December listening hours across years.");
    setText("#topChartTitle", "Podcasts by listens", "Podcasts by hours");
    const metricHead = $("#topTableMetricHead");
    if (metricHead) metricHead.textContent = hours ? "Hours" : "Eps";
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
    const px = Math.max(180, Math.min(640, 36 + n * 28));
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
    state.charts[key] = new Chart(canvas, {
      type: "bar",
      data: {
        labels: visible.map((d) => {
          const lab = String(labelOf(d) || "");
          return lab.length > 34 ? lab.slice(0, 32) + "…" : lab;
        }),
        datasets: [
          {
            label,
            data: visible.map(valueOf),
            backgroundColor: colors
              ? visible.map((_, i) => colors[i % colors.length])
              : color || palette().teal,
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
        plugins: {
          legend: { display: false },
          tooltip: {
            ...baseChartOptions().plugins.tooltip,
            callbacks: {
              label: (ctx) => {
                const v = ctx.parsed.x ?? ctx.parsed.y ?? ctx.raw;
                return `${label}: ${fmtMetric(v)}`;
              },
            },
          },
        },
      }),
    });
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
    for (let n = 0; n < matchedIdxs.length; n++) {
      const i = matchedIdxs[n];
      const e = eps[i];
      episodeCount += 1;
      const h = epHours ? epHours[i] : parseDurHours(e.dur);
      hoursTotal += h;
      if (e.prog !== "" && e.prog != null && !Number.isNaN(Number(e.prog))) {
        progressSum += Number(e.prog);
        progressN += 1;
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
        bump(byThemeHours, tid, h);
        bump(byThemeCount, tid, 1);
        if (needThemeYear && year) {
          if (!byThemeYearHours[tid]) byThemeYearHours[tid] = Object.create(null);
          if (!byThemeYearCount[tid]) byThemeYearCount[tid] = Object.create(null);
          bump(byThemeYearHours[tid], year, h);
          bump(byThemeYearCount[tid], year, 1);
        } else if (needThemeMonth && month.length === 7) {
          if (!byThemeMonthHours[tid]) byThemeMonthHours[tid] = Object.create(null);
          if (!byThemeMonthCount[tid]) byThemeMonthCount[tid] = Object.create(null);
          bump(byThemeMonthHours[tid], month, h);
          bump(byThemeMonthCount[tid], month, 1);
        } else if (needThemeDate && date) {
          if (!byThemeDateHours[tid]) byThemeDateHours[tid] = Object.create(null);
          if (!byThemeDateCount[tid]) byThemeDateCount[tid] = Object.create(null);
          bump(byThemeDateHours[tid], date, h);
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

  function metricSeriesFromMonthMap(hoursMap, countMap) {
    return seriesFromMap(metricIsHours() ? hoursMap : countMap, metricIsHours());
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
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
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
          ticks: { color: chrome.muted, maxRotation: 0, autoSkipPadding: 12 },
          grid: { color: chrome.grid },
        },
        y: {
          beginAtZero: true,
          ticks: { color: chrome.muted },
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

  function listeningDateSpan(stats) {
    const dates = Object.keys(stats.byDateCount || {}).sort();
    if (!dates.length) return "—";
    if (dates.length === 1) return formatDateShort(dates[0]);
    return `${formatDateShort(dates[0])} – ${formatDateShort(dates[dates.length - 1])}`;
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
    const span = listeningDateSpan(stats);
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
      ["Span", span],
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
    const daily = !!(state.chartPeriod.year && state.chartPeriod.month);
    if (daily) {
      return metricSeriesFromMonthMap(stats.byDateHours, stats.byDateCount);
    }
    if (!chartPeriodActive() && !metricIsHours()) {
      const monthly = state.agg.monthly || [];
      return {
        points: monthly,
        rolling: state.agg.monthlyRolling3 || [],
        cumulative: state.agg.cumulative || [],
      };
    }
    return metricSeriesFromMonthMap(stats.byMonthHours, stats.byMonthCount);
  }

  function renderTrendChart() {
    const hours = metricIsHours();
    const daily = !!(state.chartPeriod.year && state.chartPeriod.month);
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
    if (state.chartPeriod.month) {
      const src = hours ? stats.byDateHours : stats.byDateCount;
      return Object.keys(src)
        .sort()
        .map((date) => {
          const label = formatDateKey(date);
          return {
            year: label,
            label,
            count: hours ? Math.round(src[date] * 10) / 10 : src[date],
          };
        });
    }
    if (state.chartPeriod.year) {
      const src = hours ? stats.byMonthHours : stats.byMonthCount;
      return Object.keys(src)
        .sort()
        .map((ym) => {
          const label = formatMonthKey(ym);
          return {
            year: label,
            label,
            count: hours ? Math.round(src[ym] * 10) / 10 : src[ym],
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
    const src = hours ? stats.byYearHours : stats.byYearCount;
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
          year: state.chartPeriod.year,
          month: state.chartPeriod.month,
          day: state.chartPeriod.day,
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

  function renderYoYChart() {
    const hostNote = $("#yoyChartNote");
    const canvas = $("#yoyChart");
    const panel = canvas?.closest(".panel");
    // YoY comparison needs multiple years — hide when narrowed to a month/day.
    if (state.chartPeriod.month || state.chartPeriod.day) {
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
    let years = (state.agg.meta.years || []).slice().reverse();
    if (state.chartPeriod.year) years = [String(state.chartPeriod.year)];
    const dashes = [[], [6, 4], [2, 3], [8, 3, 2, 3], [], [6, 4], [2, 3], [8, 3, 2, 3]];
    if (hostNote && state.chartPeriod.year) {
      hostNote.textContent = metricIsHours()
        ? `Month-by-month hours in ${state.chartPeriod.year}.`
        : `Month-by-month episodes in ${state.chartPeriod.year}.`;
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
    if (chartPeriodActive()) {
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
      cur.hours += episodeHours(e, i);
      byPod.set(name, cur);
    }
    return [...byPod.values()].map((p) => ({
      ...p,
      hours: Math.round(p.hours * 10) / 10,
    }));
  }

  function jumpToThemePodcast(podcastName) {
    if (!podcastName) return;
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
      colors: categorical(),
      onClick: (d) => jumpToThemePodcast(d?.name),
    });
  }

  /** @deprecated name kept as alias while call sites migrate */
  function renderThemePodcastCharts() {
    renderThemeMatchPanel();
  }

  function displayThemeTags(ids) {
    // Prefer child tags; keep parent only when no child of that parent is present.
    const set = new Set(ids || []);
    const keep = [];
    for (const id of ids || []) {
      const t = state.themeById[id];
      if (!t) continue;
      if (t.parentId) {
        keep.push(id);
        continue;
      }
      const kids = (t.children || []).map((c) => c.id);
      if (!kids.some((k) => set.has(k))) keep.push(id);
    }
    // If hierarchy not loaded yet, fall back
    return keep.length ? keep : ids || [];
  }

  function themeIdsForIndex(i) {
    return (state.episodeThemes && state.episodeThemes[i]) || [];
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
    const parent = state.themeById[state.focusedParentId];
    if (parent?.children?.length) return themesPresentInFilter(parent.children);
    return themesPresentInFilter(parentThemes());
  }

  function leaveThemeDrill() {
    state.focusedParentId = "";
    state.barReveal.theme = BAR_PAGE;
    selectTheme("", false);
  }

  function renderThemeChart() {
    if (!state.themesDoc?.themes) return;
    const items = themeChartItems();
    const title = $("#themeChartTitle");
    const back = $("#themeChartBack");
    const drilled = !!state.focusedParentId;
    const parent = drilled ? state.themeById[state.focusedParentId] : null;
    const child = state.themeById[state.activeTheme];
    const viewingChild = !!(child?.parentId && child.parentId === state.focusedParentId);
    const periodLabel = chartPeriodActive()
      ? chartPeriodLabel({ omitTheme: drilled })
      : "";
    const yearSuffix = periodLabel && periodLabel !== "All time" ? ` · ${periodLabel}` : "";
    if (title) {
      if (drilled) {
        // Hierarchy: parent name as screen title; child name when one is selected.
        title.textContent = viewingChild
          ? `${child.name}${yearSuffix}`
          : `${parent?.name || "Theme"}${yearSuffix}`;
      } else {
        title.textContent = `Parent themes${yearSuffix}`;
      }
    }
    if (back) {
      const label = back.querySelector(".theme-nav-back-label");
      back.hidden = !drilled;
      if (label) {
        // One level up: child → parent children, or children → all parents.
        label.textContent = viewingChild ? parent?.name || "Themes" : "Themes";
      }
      back.setAttribute(
        "aria-label",
        viewingChild
          ? `Back to ${parent?.name || "parent theme"}`
          : "Back to parent themes"
      );
      back.onclick = drilled
        ? () => {
            if (viewingChild) {
              // Step up to the parent’s child list (keep parent filter).
              state.barReveal.theme = BAR_PAGE;
              focusParentTheme(state.focusedParentId);
              return;
            }
            leaveThemeDrill();
          }
        : null;
    }
    renderExpandableHBar({
      key: "theme",
      canvasSel: "#themeChart",
      boxSel: "#themeChartBox",
      moreSel: "#themeChartMore",
      items,
      labelOf: (d) => d.name,
      valueOf: (d) => themeMetricInYears(d),
      color: palette().teal,
      onClick: (d) => {
        if (!d?.id) return;
        if (!d.parentId) focusParentTheme(d.id);
        else selectTheme(d.id, false);
      },
    });
  }

  function themeYearSeriesThemes() {
    const active = state.themeById[state.activeTheme];
    if (active && themeMetricInYears(active) > 0) return [active];
    const parent = state.themeById[state.focusedParentId];
    if (parent?.children?.length) {
      return themesPresentInFilter(parent.children)
        .slice()
        .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a))
        .slice(0, 6);
    }
    return themesPresentInFilter(parentThemes())
      .slice()
      .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a))
      .slice(0, 6);
  }

  function themeTrendGrain() {
    const { year, month } = state.chartPeriod;
    if (year && month) return "day";
    if (year) return "month";
    return "year";
  }

  function themeTrendBuckets() {
    const stats = ensureChartStats({ ignoreTheme: true });
    const grain = themeTrendGrain();
    const { year, month } = state.chartPeriod;
    if (grain === "day") {
      const prefix = `${year}-${month}-`;
      return Object.keys(stats.byDateCount || {})
        .filter((d) => d.startsWith(prefix))
        .sort();
    }
    if (grain === "month") {
      const prefix = `${year}-`;
      return Object.keys(stats.byMonthCount || {})
        .filter((m) => m.startsWith(prefix))
        .sort();
    }
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
          ? `Top themes by hours across ${grainWord} — scoped by the filter bar above.`
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
    const t = state.themeById[themeId] || state.themeById[state.focusedParentId];
    const title = $("#themeDetailTitle");
    const blurb = $("#themeDetailBlurb");
    const samples = $("#themeSamples");
    const btn = $("#filterByTheme");
    if (!t) {
      title.textContent = "Pick a theme";
      blurb.textContent =
        "Tap a parent to open child themes derived from episode content, then filter the explorer. The sticky filter bar scopes counts and samples.";
      samples.innerHTML = "";
      btn.hidden = true;
      return;
    }
    const kind = t.parentId ? "Child theme" : "Parent theme";
    const n = themeMetricInYears(t);
    const periodSuffix = chartPeriodActive() ? ` in ${chartPeriodLabel()}` : "";
    const unit = metricIsHours() ? "hours" : "episodes";
    const ev = t.evidence || {};
    const evBits = [
      ev.transcript ? `${fmt(ev.transcript)} transcript-backed` : "",
      ev.notes ? `${fmt(ev.notes)} notes-backed` : "",
      ev.title ? `${fmt(ev.title)} title-only` : "",
    ].filter(Boolean);
    title.textContent = t.name;
    blurb.textContent = `${kind}. ${t.blurb} · ${fmtMetric(n)} ${unit}${periodSuffix}.${
      evBits.length ? ` Evidence: ${evBits.join(", ")}.` : ""
    }`;
    const samplesList = (t.samples || []).filter(sampleMatchesChartPeriod);
    samples.innerHTML = samplesList
      .map(
        (s) => `
      <div class="theme-sample">
        <strong>${escapeHtml(s.e || "")}</strong>
        <span>${escapeHtml(s.p || "Podcast")} · ${escapeHtml(formatUiDate(s.d || ""))}</span>
      </div>`
      )
      .join("") ||
      `<div class="empty">No samples${periodSuffix || " yet"}.</div>`;
    btn.hidden = false;
    btn.onclick = () => selectTheme(t.id, true);
  }

  function focusParentTheme(parentId) {
    state.barReveal.theme = BAR_PAGE;
    const patch = { theme: parentId || "" };
    if (parentId) patch.q = "";
    patchChartPeriod(patch);
  }

  function selectTheme(themeId, jumpExplore) {
    const t = state.themeById[themeId];
    if (t && !t.parentId && (t.children || []).length) {
      focusParentTheme(themeId);
      if (jumpExplore) {
        goToSection("explorePanel");
      }
      return;
    }
    const patch = { theme: themeId || "" };
    if (themeId) patch.q = "";
    patchChartPeriod(patch);
    if (jumpExplore) {
      goToSection("explorePanel");
    }
  }

  function renderTopTable() {
    const hours = metricIsHours();
    const all = topPodcastItems()
      .slice()
      .sort((a, b) => (hours ? b.hours - a.hours : b.count - a.count) || a.name.localeCompare(b.name));
    if (state.tableReveal.top == null) state.tableReveal.top = BAR_PAGE;
    const shown = Math.min(state.tableReveal.top, all.length);
    const max = (hours ? all[0]?.hours : all[0]?.count) || 1;
    const body = all
      .slice(0, shown)
      .map((p, i) => {
        const val = hours ? p.hours : p.count;
        return `
      <tr>
        <td>${i + 1}</td>
        <td><button type="button" class="linkish" data-podcast="${escapeHtml(p.name)}">${escapeHtml(p.name)}</button></td>
        <td>${fmtMetric(val)}</td>
        <td><div class="bar"><span style="width:${(val / max) * 100}%"></span></div></td>
      </tr>`;
      })
      .join("");
    $("#topTable tbody").innerHTML = body;
    $$("#topTable [data-podcast]").forEach((btn) => {
      btn.addEventListener("click", () => {
        patchChartPeriod({ podcast: btn.dataset.podcast });
        goToSection("explorePanel");
      });
    });
    const more = $("#topTableMore");
    if (more) {
      const remaining = all.length - shown;
      const parts = [];
      if (remaining > 0) {
        parts.push(
          `<button type="button" class="btn secondary" data-more="1">Show more (${fmt(remaining)} left)</button>`
        );
      }
      if (shown > BAR_PAGE) {
        parts.push(`<button type="button" class="btn secondary" data-less="1">Show less</button>`);
      }
      more.innerHTML = parts.join("");
      more.querySelector("[data-more]")?.addEventListener("click", () => {
        state.tableReveal.top = Math.min(all.length, shown + BAR_PAGE);
        renderTopTable();
      });
      more.querySelector("[data-less]")?.addEventListener("click", () => {
        state.tableReveal.top = BAR_PAGE;
        renderTopTable();
      });
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
    $("#periodYear")?.addEventListener("change", (e) => {
      patchChartPeriod({ year: e.target.value, month: "", day: "" });
    });
    $("#periodMonth")?.addEventListener("change", (e) => {
      patchChartPeriod({ month: e.target.value, day: "" });
    });
    $("#periodDay")?.addEventListener("change", (e) => {
      patchChartPeriod({ day: e.target.value });
    });
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
        year: "",
        month: "",
        day: "",
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
      const open = !document.body.classList.contains("filter-sheet-open");
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
      if (document.body.classList.contains("filter-sheet-open")) {
        setFilterSheetOpen(false);
      }
    });
    const onViewport = () => {
      if (document.body.classList.contains("combo-picker-open")) syncVisualViewportVars();
    };
    window.visualViewport?.addEventListener("resize", onViewport);
    window.visualViewport?.addEventListener("scroll", onViewport);
    window.matchMedia("(max-width: 860px)").addEventListener("change", (e) => {
      closeComboPicker(false);
      if (!e.matches) setFilterSheetOpen(false);
      else placeFilterPanel(false);
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
      const [agg, episodes, podcasts, themesDoc, episodeThemes, notes, countriesDoc] =
        await loadAll();
      state.agg = agg;
      state.episodes = episodes;
      state.podcasts = podcasts;
      state.themesDoc = themesDoc;
      state.episodeThemes = episodeThemes;
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

      $("#exportedAt").textContent = `Snapshot ${formatUiDate(agg.meta.exportedAt?.slice(0, 10) || "")}`;
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
      renderTopTable();
      renderThemeChart();
      renderThemeYearChart();
      renderThemePodcastCharts();
      renderThemeDetail("");
      renderEpisodeList();
      wire();
      document.body.classList.add("ready");
      $("#bootStatus").textContent = "";
      showTab(activeTabId, { scrollTop: false });
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
