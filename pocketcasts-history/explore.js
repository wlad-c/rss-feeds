/* Pocket Casts listening explore app */
(() => {
  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  /* High-contrast categorical palette (Okabe–Ito + extras); hues stay far apart */
  const THEME_KEY = "listening-log-theme";
  const METRIC_KEY = "listening-log-metric";
  const COLORS = {
    ink: "#243447",
    muted: "#5b6b7c",
    blue: "#0072B2",
    amber: "#E69F00",
    teal: "#009E73",
    vermillion: "#D55E00",
    sky: "#56B4E9",
    olive: "#6A8F00",
    rose: "#CC79A7",
    rust: "#A15C00",
    slate: "#4A5568",
    navy: "#0B3D6E",
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
  const state = {
    agg: null,
    episodes: null,
    podcasts: null,
    themesDoc: null,
    episodeThemes: null,
    notes: null,
    themeById: {},
    activeTheme: "",
    focusedParentId: "",
    themeYears: [], // empty = all years; multi-select from themes panel
    metric: "episodes", // "episodes" | "hours"
    chartPeriod: { year: "", month: "", day: "" },
    charts: {},
    barReveal: {},
    tableReveal: { top: 12 },
    filters: { year: "all", podcast: "", q: "", status: "", theme: "" },
    page: 0,
    pageSize: 40,
    _chartStats: null,
    _chartStatsKey: "",
    _localStats: null,
    _periodIndex: null,
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

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

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
      rerenderCharts();
      renderHeatmap();
      renderTopTable();
      refreshThemeViews();
      updatePeriodSummary();
    }
  }

  function syncMetricToggle() {
    $$("[data-metric]").forEach((btn) => {
      const on = btn.dataset.metric === state.metric;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function chartPeriodActive() {
    const { year, month, day } = state.chartPeriod;
    return !!(year || month || day);
  }

  function chartPeriodKey() {
    const { year, month, day } = state.chartPeriod;
    return `${year || "all"}|${month || "all"}|${day || "all"}`;
  }

  function chartPeriodLabel() {
    const { year, month, day } = state.chartPeriod;
    if (!year) return "All time";
    if (!month) return String(year);
    const monthLabel = MONTH_NAME[month] || month;
    if (!day) return `${monthLabel} ${year}`;
    return `${Number(day)} ${monthLabel} ${year}`;
  }

  function episodeMatchesChartPeriod(e) {
    const { year, month, day } = state.chartPeriod;
    if (!year && !month && !day) return true;
    const d = String(e.d || "");
    if (year && String(e.y) !== String(year)) return false;
    if (month && d.slice(5, 7) !== month) return false;
    if (day && d.slice(8, 10) !== day) return false;
    return true;
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
    state._localStats = null;
  }

  function applyChartPeriod(next, { rerender = true } = {}) {
    const year = next.year ? String(next.year) : "";
    const month = year && next.month ? String(next.month).padStart(2, "0") : "";
    const day = year && month && next.day ? String(next.day).padStart(2, "0") : "";
    state.chartPeriod = { year, month, day };
    invalidateChartStats();
    syncPeriodControls();
    updateMetricLabels();
    updatePeriodSummary();
    if (!rerender || !state.agg) return;
    if (year) {
      state.filters.year = year;
      if ($("#yearFilter")) $("#yearFilter").value = year;
    } else {
      state.filters.year = "all";
      if ($("#yearFilter")) $("#yearFilter").value = "all";
    }
    state.page = 0;
    state.barReveal.top = BAR_PAGE;
    state.tableReveal.top = BAR_PAGE;
    rerenderCharts();
    renderHeatmap();
    renderTopTable();
    refreshThemeViews();
    renderEpisodeList();
  }

  function syncPeriodControls() {
    const yearSel = $("#periodYear");
    const monthSel = $("#periodMonth");
    const daySel = $("#periodDay");
    if (!yearSel || !monthSel || !daySel) return;
    const idx = ensurePeriodIndex();
    const { year, month, day } = state.chartPeriod;
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
  }

  function updatePeriodSummary() {
    const el = $("#periodSummary");
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

  function chartChrome() {
    if (isDark()) {
      return {
        label: "#f3f7fc",
        muted: "#c2d0de",
        grid: "rgba(243,247,252,.12)",
        tooltipBg: "#0b1220",
        doughnutBorder: "#1c2838",
      };
    }
    return {
      label: "#243447",
      muted: "#5b6b7c",
      grid: "rgba(20,32,51,.08)",
      tooltipBg: "#142033",
      doughnutBorder: "#ffffff",
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
    if (state.charts[key]) {
      state.charts[key].destroy();
      delete state.charts[key];
    }
  }

  function ensureBarReveal(key, total) {
    if (state.barReveal[key] == null) state.barReveal[key] = Math.min(BAR_PAGE, total);
    state.barReveal[key] = Math.min(Math.max(state.barReveal[key], 1), total);
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

  /** Horizontal bar chart: largest at top, progressive disclosure. */
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
  }) {
    const sorted = items
      .slice()
      .sort((a, b) => valueOf(b) - valueOf(a) || String(labelOf(a)).localeCompare(String(labelOf(b))));
    const total = sorted.length;
    const shown = ensureBarReveal(key, total || 1);
    const visible = sorted.slice(0, shown);
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
              : color || COLORS.teal,
            borderRadius: 5,
            maxBarThickness: 22,
          },
        ],
      },
      options: baseChartOptions({
        indexAxis: "y",
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
        onClick: onClick
          ? (_evt, elements) => {
              if (!elements.length) return;
              onClick(visible[elements[0].index], elements[0].index);
            }
          : undefined,
      }),
    });
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
      })
    );
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

  function ensureChartStats() {
    const key = chartPeriodKey();
    if (state._chartStats && state._chartStatsKey === key) return state._chartStats;

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
    const byStatusHours = Object.create(null);
    const byStatusCount = Object.create(null);
    const byThemeHours = Object.create(null);
    const byThemeCount = Object.create(null);
    const byThemeYearHours = Object.create(null);
    const byThemeYearCount = Object.create(null);
    const hourHours = Array.from({ length: 24 }, () => 0);
    const weekdayHours = Array.from({ length: 7 }, () => 0);
    const hourCounts = Array.from({ length: 24 }, () => 0);
    const weekdayCounts = Array.from({ length: 7 }, () => 0);
    const yearMinutes = Object.create(null);
    const yearMinuteSamples = Object.create(null);

    let episodeCount = 0;
    let hoursTotal = 0;
    const eps = state.episodes || [];
    for (let i = 0; i < eps.length; i++) {
      const e = eps[i];
      if (!episodeMatchesChartPeriod(e)) continue;
      episodeCount += 1;
      const h = parseDurHours(e.dur);
      hoursTotal += h;
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

      const themes = (state.episodeThemes && state.episodeThemes[i]) || [];
      for (const tid of themes) {
        bump(byThemeHours, tid, h);
        bump(byThemeCount, tid, 1);
        if (!year) continue;
        if (!byThemeYearHours[tid]) byThemeYearHours[tid] = Object.create(null);
        if (!byThemeYearCount[tid]) byThemeYearCount[tid] = Object.create(null);
        bump(byThemeYearHours[tid], year, h);
        bump(byThemeYearCount[tid], year, 1);
      }
    }

    const avgDurationByYear = Object.keys(yearMinutes)
      .sort()
      .map((year) => ({
        year: Number(year),
        avgMinutes:
          Math.round(((yearMinutes[year] || 0) / (yearMinuteSamples[year] || 1)) * 10) / 10,
      }));

    state._chartStats = {
      episodeCount,
      hoursTotal: Math.round(hoursTotal * 10) / 10,
      podcastCount: Object.keys(byPodcastCount).length,
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
      byStatusHours,
      byStatusCount,
      byThemeHours,
      byThemeCount,
      byThemeYearHours,
      byThemeYearCount,
      hourHours,
      weekdayHours,
      hourCounts,
      weekdayCounts,
      avgDurationByYear,
    };
    state._chartStatsKey = key;
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
    renderDurationChart();
    renderThemeChart();
    renderThemeYearChart();
    renderThemePodcastCharts();
  }

  async function hardRefresh() {
    const btn = $("#hardRefresh");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Refreshing…";
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

  function renderHeroStats(meta) {
    const items = [
      ["Episodes", fmt(meta.totalEpisodes)],
      ["Podcasts", fmt(meta.totalPodcasts)],
      ["Hours", fmt(Math.round(meta.totalDurationHours || 0))],
      ["Avg length", `${meta.avgEpisodeMinutes ?? "—"}m`],
      ["Finish rate", meta.avgProgressPct != null ? `${meta.avgProgressPct}%` : "—"],
      ["Span", `${meta.years?.[meta.years.length - 1] ?? ""}–${meta.years?.[0] ?? ""}`],
    ];
    $("#heroStats").innerHTML = items
      .map(
        ([k, v]) =>
          `<div class="stat"><b>${escapeHtml(v)}</b><span>${escapeHtml(k)}</span></div>`
      )
      .join("");

    const strip = $("#insightStrip");
    const bits = [];
    if (meta.busiestMonth) {
      bits.push(
        `<div class="insight"><b>${escapeHtml(meta.busiestMonth.month)} · ${fmt(meta.busiestMonth.count)}</b><span>Busiest month by episodes played</span></div>`
      );
    }
    if (meta.busiestDay) {
      bits.push(
        `<div class="insight"><b>${escapeHtml(meta.busiestDay.date)} · ${fmt(meta.busiestDay.count)}</b><span>Most active single day</span></div>`
      );
    }
    if (meta.top5SharePct != null) {
      bits.push(
        `<div class="insight"><b>${escapeHtml(String(meta.top5SharePct))}%</b><span>Of all listens come from your top 5 shows</span></div>`
      );
    }
    if (meta.accountStartedAt && meta.perEpisodeHistoryFrom) {
      const started = String(meta.accountStartedAt).slice(0, 10);
      bits.push(
        `<div class="insight"><b>${escapeHtml(started)} → ${escapeHtml(meta.perEpisodeHistoryFrom)}</b><span>Account age vs first per-episode history (Pocket Casts has no listen rows for 2010–2018)</span></div>`
      );
    }
    if (bits.length) {
      strip.hidden = false;
      strip.innerHTML = bits.join("");
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
        borderColor: COLORS.blue,
        backgroundColor: "rgba(0,114,178,.14)",
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
        borderColor: COLORS.amber,
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
        labels: points.map((m) => m.month),
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
        labels: cumulative.map((d) => d.month),
        datasets: [
          {
            label: hours ? "Cumulative hours" : "Cumulative episodes",
            data: cumulative.map((d) => d.total),
            borderColor: COLORS.navy,
            backgroundColor: "rgba(11,61,110,.12)",
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
        .map((date) => ({
          year: date.slice(8, 10),
          label: date.slice(8, 10),
          count: hours ? Math.round(src[date] * 10) / 10 : src[date],
        }));
    }
    if (state.chartPeriod.year) {
      const src = hours ? stats.byMonthHours : stats.byMonthCount;
      return Object.keys(src)
        .sort()
        .map((ym) => ({
          year: MONTH_NAME[ym.slice(5, 7)] || ym.slice(5, 7),
          label: MONTH_NAME[ym.slice(5, 7)] || ym.slice(5, 7),
          count: hours ? Math.round(src[ym] * 10) / 10 : src[ym],
        }));
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
      color: COLORS.blue,
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
      colors: CATEGORICAL,
      onClick: (d) => {
        if (!d?.name) return;
        state.filters.podcast = d.name;
        $("#podcastFilter").value = d.name;
        state.page = 0;
        $("#explorePanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
        renderEpisodeList();
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
      color: COLORS.vermillion,
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
            borderColor: COLORS.teal,
            backgroundColor: "rgba(0,158,115,.14)",
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
      colors: CATEGORICAL,
    });

    destroyChart("status");
    state.charts.status = new Chart($("#statusChart"), {
      type: "doughnut",
      data: {
        labels: statusItems.map((d) => d.name),
        datasets: [
          {
            data: statusItems.map((d) => d.count),
            backgroundColor: [COLORS.teal, COLORS.amber, COLORS.slate, COLORS.blue],
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
      color: COLORS.amber,
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
          borderColor: CATEGORICAL[i % CATEGORICAL.length],
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
        return `<div class="heat-cell" data-level="${level}" title="${escapeHtml(c.date)}: ${escapeHtml(unit)}"></div>`;
      })
      .join("");
  }

  function populateFilters() {
    const yearSel = $("#yearFilter");
    yearSel.innerHTML =
      `<option value="all">All years</option>` +
      state.agg.meta.years
        .map((y) => `<option value="${y}">${y} (${fmt(state.agg.meta.yearCounts[y])})</option>`)
        .join("");

    const podSel = $("#podcastFilter");
    const names = state.agg.topPodcasts.map((p) => p.name);
    podSel.innerHTML =
      `<option value="">All podcasts</option>` +
      names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("");

    const themeSel = $("#themeFilter");
    if (themeSel && state.themesDoc?.themes) {
      const opts = ['<option value="">All themes</option>'];
      for (const p of state.themesDoc.themes) {
        opts.push(
          `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${fmt(p.count)})</option>`
        );
        for (const c of p.children || []) {
          opts.push(
            `<option value="${escapeHtml(c.id)}">↳ ${escapeHtml(c.name)} (${fmt(c.count)})</option>`
          );
        }
      }
      themeSel.innerHTML = opts.join("");
    }
  }

  function parentThemes() {
    return state.themesDoc?.themes || [];
  }

  function flatThemes() {
    return state.themesDoc?.flat || parentThemes();
  }

  function availableThemeYears() {
    const fromAgg = state.agg?.meta?.years || [];
    if (fromAgg.length) return fromAgg.map(String);
    const years = new Set();
    for (const t of flatThemes()) {
      Object.keys(t.byYear || {}).forEach((y) => years.add(String(y)));
    }
    return [...years].sort((a, b) => Number(b) - Number(a));
  }

  function selectedThemeYearSet() {
    if (!state.themeYears?.length) return null;
    return new Set(state.themeYears.map(String));
  }

  function themeCountInYears(t) {
    if (!t) return 0;
    if (chartPeriodActive()) {
      return ensureChartStats().byThemeCount[t.id] || 0;
    }
    const years = selectedThemeYearSet();
    if (!years) return t.count || 0;
    let n = 0;
    for (const y of years) n += Number(t.byYear?.[y] || 0);
    return n;
  }

  function themeHoursInYears(t) {
    if (!t) return 0;
    const stats = ensureChartStats();
    if (chartPeriodActive()) return stats.byThemeHours[t.id] || 0;
    const years = selectedThemeYearSet();
    if (!years) return stats.byThemeHours[t.id] || 0;
    let n = 0;
    const byYear = stats.byThemeYearHours[t.id] || {};
    for (const y of years) n += Number(byYear[y] || 0);
    return n;
  }

  function themeMetricInYears(t) {
    return metricIsHours() ? themeHoursInYears(t) : themeCountInYears(t);
  }

  function themeMetricLabel(n) {
    return metricIsHours() ? `${fmtHours(n)}h` : fmt(n);
  }

  function themeYearLabel() {
    const years = availableThemeYears();
    if (!state.themeYears.length || state.themeYears.length === years.length) {
      return "All years";
    }
    const sorted = state.themeYears.slice().sort((a, b) => Number(a) - Number(b));
    if (sorted.length <= 2) return sorted.join(", ");
    return `${sorted[0]}–${sorted[sorted.length - 1]} · ${sorted.length}`;
  }

  function episodeMatchesThemeYears(ep) {
    const years = selectedThemeYearSet();
    if (!years) return true;
    return years.has(String(ep.y));
  }

  function sampleInThemeYears(s) {
    const years = selectedThemeYearSet();
    if (!years) return true;
    const y = String(s?.d || "").slice(0, 4);
    return years.has(y);
  }

  function refreshThemeViews() {
    renderThemeYearControls();
    renderThemeChips();
    renderThemeChart();
    renderThemeYearChart();
    renderThemePodcastCharts();
    renderThemeDetail(state.activeTheme || state.focusedParentId || "");
    renderEpisodeList();
  }

  function activeThemeForPodcasts() {
    return (
      state.themeById[state.activeTheme] ||
      state.themeById[state.focusedParentId] ||
      null
    );
  }

  function episodeMatchesThemeId(thIds, themeId) {
    if (!themeId) return false;
    return (thIds || []).includes(themeId);
  }

  function podcastsForTheme(themeId) {
    if (!themeId || !state.episodes?.length) return [];
    const themeYears = selectedThemeYearSet();
    const byPod = new Map();
    for (let i = 0; i < state.episodes.length; i++) {
      const e = state.episodes[i];
      if (chartPeriodActive()) {
        if (!episodeMatchesChartPeriod(e)) continue;
      } else if (themeYears && !episodeMatchesThemeYears(e)) {
        continue;
      }
      const th = themeIdsForIndex(i);
      if (!episodeMatchesThemeId(th, themeId)) continue;
      const name = e.p || "Unknown";
      const cur = byPod.get(name) || { name, count: 0, hours: 0 };
      cur.count += 1;
      cur.hours += parseDurHours(e.dur);
      byPod.set(name, cur);
    }
    return [...byPod.values()].map((p) => ({
      ...p,
      hours: Math.round(p.hours * 10) / 10,
    }));
  }

  function jumpToThemePodcast(podcastName) {
    if (!podcastName) return;
    state.filters.podcast = podcastName;
    if ($("#podcastFilter")) $("#podcastFilter").value = podcastName;
    state.page = 0;
    renderEpisodeList();
    $("#explorePanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderThemePodcastCharts() {
    const theme = activeThemeForPodcasts();
    const epsTitle = $("#themePodEpsTitle");
    const hoursTitle = $("#themePodHoursTitle");
    const epsNote = $("#themePodEpsNote");
    const hoursNote = $("#themePodHoursNote");
    const scope = chartPeriodActive()
      ? chartPeriodLabel()
      : state.themeYears.length
        ? themeYearLabel()
        : "all years";

    if (!theme) {
      if (epsTitle) epsTitle.textContent = "Shows covering this theme · episodes";
      if (hoursTitle) hoursTitle.textContent = "Shows covering this theme · hours";
      if (epsNote) {
        epsNote.textContent =
          "Pick a parent or child theme to see which podcasts contribute the most episodes.";
      }
      if (hoursNote) {
        hoursNote.textContent =
          "Pick a theme to rank the same shows by listening time (episode duration).";
      }
      renderExpandableHBar({
        key: "themePodEps",
        canvasSel: "#themePodEpsChart",
        boxSel: "#themePodEpsBox",
        moreSel: "#themePodEpsMore",
        items: [],
        labelOf: (d) => d.name,
        valueOf: (d) => d.count,
        colors: CATEGORICAL,
      });
      renderExpandableHBar({
        key: "themePodHours",
        canvasSel: "#themePodHoursChart",
        boxSel: "#themePodHoursBox",
        moreSel: "#themePodHoursMore",
        items: [],
        labelOf: (d) => d.name,
        valueOf: (d) => d.hours,
        colors: CATEGORICAL,
      });
      return;
    }

    const items = podcastsForTheme(theme.id);
    const byEps = items.slice().sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    const byHours = items
      .slice()
      .sort((a, b) => b.hours - a.hours || a.name.localeCompare(b.name));
    const topEps = byEps[0];
    const topHours = byHours[0];

    if (epsTitle) epsTitle.textContent = `${theme.name} · shows by episodes`;
    if (hoursTitle) hoursTitle.textContent = `${theme.name} · shows by hours`;
    if (epsNote) {
      epsNote.textContent = topEps
        ? `${fmt(byEps.length)} shows in ${scope}. Most episodes: ${topEps.name} (${fmt(topEps.count)}). Tap a bar to filter Explore.`
        : `No matching episodes for ${theme.name} in ${scope}.`;
    }
    if (hoursNote) {
      hoursNote.textContent = topHours
        ? `${fmt(byHours.length)} shows in ${scope}. Most time: ${topHours.name} (${fmtHours(topHours.hours)}h). Tap a bar to filter Explore.`
        : `No matching listening time for ${theme.name} in ${scope}.`;
    }

    renderExpandableHBar({
      key: "themePodEps",
      canvasSel: "#themePodEpsChart",
      boxSel: "#themePodEpsBox",
      moreSel: "#themePodEpsMore",
      items: byEps,
      labelOf: (d) => d.name,
      valueOf: (d) => d.count,
      colors: CATEGORICAL,
      onClick: (d) => jumpToThemePodcast(d?.name),
    });
    renderExpandableHBar({
      key: "themePodHours",
      canvasSel: "#themePodHoursChart",
      boxSel: "#themePodHoursBox",
      moreSel: "#themePodHoursMore",
      items: byHours,
      labelOf: (d) => d.name,
      valueOf: (d) => d.hours,
      colors: CATEGORICAL,
      onClick: (d) => jumpToThemePodcast(d?.name),
    });
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
    const { year, podcast, q, status, theme } = state.filters;
    const qq = q.trim().toLowerCase();
    const themeYears = selectedThemeYearSet();
    const out = [];
    for (let i = 0; i < state.episodes.length; i++) {
      const e = state.episodes[i];
      if (chartPeriodActive()) {
        if (!episodeMatchesChartPeriod(e)) continue;
      } else if (themeYears) {
        if (!episodeMatchesThemeYears(e)) continue;
      } else if (year !== "all" && String(e.y) !== String(year)) {
        continue;
      }
      if (podcast && e.p !== podcast) continue;
      if (status && e.st !== status) continue;
      const th = themeIdsForIndex(i);
      if (theme && !th.includes(theme)) continue;
      if (qq) {
        const themeNames = th
          .map((id) => state.themeById[id]?.name || id)
          .join(" ");
        const hay = `${e.e} ${e.p} ${e.a} ${e.f} ${themeNames} ${noteTextForIndex(i)}`.toLowerCase();
        if (!hay.includes(qq)) continue;
      }
      out.push({ ...e, _i: i, _th: th });
    }
    return out;
  }

  function renderEpisodeList() {
    const rows = filteredEpisodes();
    const totalPages = Math.max(1, Math.ceil(rows.length / state.pageSize));
    if (state.page >= totalPages) state.page = totalPages - 1;
    const start = state.page * state.pageSize;
    const slice = rows.slice(start, start + state.pageSize);

    $("#listMeta").textContent = `${fmt(rows.length)} matching episodes`;
    $("#episodeList").innerHTML = slice
      .map((e) => {
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
          (state.filters.q.trim()
            ? note
            : note.length > 280
              ? note.slice(0, 280) + "…"
              : note);
        return `
      <article class="ep">
        <div class="ep-show">${escapeHtml(e.p || "Podcast")}${e.f ? ` · ${escapeHtml(e.f)}` : ""}</div>
        <h3>${escapeHtml(e.e || "(untitled)")}</h3>
        <div class="ep-meta">
          <span>${escapeHtml(e.d || e.t || "")}</span>
          ${e.dur ? `<span>${escapeHtml(e.dur)}</span>` : ""}
          ${e.st ? `<span class="tag ${e.st === "Played" ? "ok" : e.st === "In progress" ? "warn" : ""}">${escapeHtml(e.st)}</span>` : ""}
          ${e.prog !== "" && e.prog != null ? `<span>${escapeHtml(e.prog)}%</span>` : ""}
          ${e.star ? `<span class="tag ok">Starred</span>` : ""}
          ${noteLabel ? `<span class="tag ${noteFull ? "ok" : ""}">${escapeHtml(noteLabel)}</span>` : ""}
        </div>
        ${themeTags ? `<div class="ep-themes">${themeTags}</div>` : ""}
        ${snippet ? `<div class="ep-note">${escapeHtml(snippet)}</div>` : ""}
      </article>`;
      })
      .join("") || `<div class="empty">No episodes match these filters.</div>`;

    $("#pageInfo").textContent = `Page ${state.page + 1} / ${totalPages}`;
    $("#prevPage").disabled = state.page <= 0;
    $("#nextPage").disabled = state.page >= totalPages - 1;

    $$("#episodeList [data-theme-jump]").forEach((btn) => {
      btn.addEventListener("click", () => selectTheme(btn.dataset.themeJump, true));
    });

    // Insights for current filter
    const byPod = {};
    const hours = metricIsHours();
    for (const e of rows) {
      const key = e.p || "Unknown";
      byPod[key] = (byPod[key] || 0) + (hours ? parseDurHours(e.dur) : 1);
    }
    const top = Object.entries(byPod).sort((a, b) => b[1] - a[1]).slice(0, 5);
    $("#filterInsights").innerHTML = top.length
      ? `<strong>In this view:</strong> ` +
        top
          .map(([n, c]) => `${escapeHtml(n)} (${fmtMetric(c)}${hours ? "h" : ""})`)
          .join(" · ")
      : "";
  }

  function renderThemeBreadcrumb() {
    const host = $("#themeBreadcrumb");
    if (!host) return;
    const parent = state.themeById[state.focusedParentId];
    if (!parent) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    host.innerHTML = `
      <button type="button" data-crumb="all">All themes</button>
      <span>›</span>
      <strong>${escapeHtml(parent.name)}</strong>`;
    host.querySelector("[data-crumb='all']")?.addEventListener("click", () => {
      state.focusedParentId = "";
      state.barReveal.theme = BAR_PAGE;
      selectTheme("", false);
    });
  }

  function renderThemeYearControls() {
    const panel = $("#themeYearPanel");
    const label = $("#themeYearLabel");
    if (label) label.textContent = themeYearLabel();
    if (!panel) return;
    const years = availableThemeYears();
    const selected = new Set(state.themeYears.map(String));
    const allSelected = !state.themeYears.length || state.themeYears.length === years.length;
    panel.innerHTML = `
      <div class="year-multi-actions">
        <button type="button" data-years="all">All years</button>
        <button type="button" data-years="none">Clear</button>
      </div>
      ${years
        .map((y) => {
          const checked = allSelected || selected.has(String(y));
          const n = state.agg?.meta?.yearCounts?.[y];
          return `<label class="year-multi-option">
            <input type="checkbox" value="${escapeHtml(y)}" ${checked ? "checked" : ""} />
            <span>${escapeHtml(y)}</span>
            ${n != null ? `<small>${fmt(n)}</small>` : ""}
          </label>`;
        })
        .join("")}`;
    panel.querySelector("[data-years='all']")?.addEventListener("click", () => {
      state.themeYears = [];
      refreshThemeViews();
    });
    panel.querySelector("[data-years='none']")?.addEventListener("click", () => {
      // Uncheck all so the next click starts a fresh multi-select; counts stay "all" until a year is checked.
      $$("input[type=checkbox]", panel).forEach((b) => {
        b.checked = false;
      });
      state.themeYears = [];
      if (label) label.textContent = "Pick years…";
    });
    $$("input[type=checkbox]", panel).forEach((box) => {
      box.addEventListener("change", () => {
        const picked = $$("input[type=checkbox]", panel)
          .filter((b) => b.checked)
          .map((b) => b.value);
        if (!picked.length) {
          state.themeYears = [];
          if (label) label.textContent = "Pick years…";
          refreshThemeViews();
          return;
        }
        state.themeYears = picked.length === years.length ? [] : picked;
        refreshThemeViews();
      });
    });
  }

  function setThemeYearPanelOpen(open) {
    const panel = $("#themeYearPanel");
    const toggle = $("#themeYearToggle");
    if (!panel || !toggle) return;
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function renderThemeChips() {
    const host = $("#themeChips");
    const childHost = $("#themeChildChips");
    if (!host || !state.themesDoc?.themes) return;
    const parents = parentThemes()
      .slice()
      .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a));
    host.innerHTML = parents
      .map(
        (t) => `
      <button type="button" class="theme-chip${
        state.focusedParentId === t.id || state.activeTheme === t.id ? " active" : ""
      }" data-theme="${escapeHtml(t.id)}">
        ${escapeHtml(t.name)}<small>${escapeHtml(themeMetricLabel(themeMetricInYears(t)))}</small>
      </button>`
      )
      .join("");
    $$(".theme-chip", host).forEach((btn) => {
      btn.addEventListener("click", () => focusParentTheme(btn.dataset.theme));
    });

    const parent = state.themeById[state.focusedParentId];
    if (childHost) {
      if (parent?.children?.length) {
        const kids = parent.children
          .slice()
          .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a));
        childHost.hidden = false;
        childHost.innerHTML = kids
          .map(
            (t) => `
          <button type="button" class="theme-chip child${
            state.activeTheme === t.id ? " active" : ""
          }" data-theme="${escapeHtml(t.id)}">
            ${escapeHtml(t.name)}<small>${escapeHtml(themeMetricLabel(themeMetricInYears(t)))}</small>
          </button>`
          )
          .join("");
        $$(".theme-chip", childHost).forEach((btn) => {
          btn.addEventListener("click", () => selectTheme(btn.dataset.theme, false));
        });
      } else {
        childHost.hidden = true;
        childHost.innerHTML = "";
      }
    }

    renderThemeBreadcrumb();
    const meta = state.themesDoc.meta || {};
    const notesN = state.notes ? Object.keys(state.notes).length : 0;
    const yearBit = chartPeriodActive()
      ? ` · ${chartPeriodLabel()}`
      : state.themeYears.length
        ? ` · years ${state.themeYears
            .slice()
            .sort((a, b) => Number(a) - Number(b))
            .join(", ")}`
        : "";
    const scoped = chartPeriodActive() ? ensureChartStats() : null;
    const noteEntries = Object.values(state.notes || {});
    const txN = noteEntries.filter((n) => n?.src === "transcript" || n?.src === "stt").length;
    const fullN = noteEntries.filter((n) => n?.full || (n?.chars || 0) > 900).length;
    const bodyN = meta.episodesWithBodyText != null ? meta.episodesWithBodyText : notesN;
    $("#themeCoverage").textContent =
      (scoped
        ? `${fmt(scoped.episodeCount)} episodes in ${chartPeriodLabel()}`
        : `${fmt(meta.episodesWithTheme || 0)} / ${fmt(meta.totalEpisodes || 0)} episodes carry at least one theme`) +
      (meta.childCount != null
        ? ` · ${fmt(meta.parentCount)} parents / ${fmt(meta.childCount)} child themes`
        : "") +
      yearBit +
      (bodyN
        ? ` · ${fmt(bodyN)} with body text (${fmt(txN)} transcript/STT, ${fmt(fullN)} longer than snippet)`
        : "") +
      `. Themes prefer transcript-backed matches when full text is stored.`;
  }

  function themeChartItems() {
    const parent = state.themeById[state.focusedParentId];
    if (parent?.children?.length) return parent.children;
    return parentThemes();
  }

  function renderThemeChart() {
    if (!state.themesDoc?.themes) return;
    const items = themeChartItems();
    const title = $("#themeChartTitle");
    const yearSuffix = chartPeriodActive()
      ? ` · ${chartPeriodLabel()}`
      : state.themeYears.length
        ? ` · ${themeYearLabel()}`
        : "";
    if (title) {
      title.textContent = state.focusedParentId
        ? `${state.themeById[state.focusedParentId]?.name || "Theme"} · child themes${yearSuffix}`
        : `Parent themes${yearSuffix}`;
    }
    renderExpandableHBar({
      key: "theme",
      canvasSel: "#themeChart",
      boxSel: "#themeChartBox",
      moreSel: "#themeChartMore",
      items,
      labelOf: (d) => d.name,
      valueOf: (d) => themeMetricInYears(d),
      color: COLORS.teal,
      onClick: (d) => {
        if (!d?.id) return;
        if (!d.parentId) focusParentTheme(d.id);
        else selectTheme(d.id, false);
      },
    });
  }

  function themeYearSeriesThemes() {
    const active = state.themeById[state.activeTheme];
    if (active?.byYear || (metricIsHours() && active)) return [active];
    const parent = state.themeById[state.focusedParentId];
    if (parent?.children?.length) {
      return parent.children
        .slice()
        .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a))
        .slice(0, 6);
    }
    return parentThemes()
      .slice()
      .sort((a, b) => themeMetricInYears(b) - themeMetricInYears(a))
      .slice(0, 6);
  }

  function themeYearValue(t, y) {
    if (metricIsHours()) {
      return Number(ensureChartStats().byThemeYearHours[t.id]?.[y] || 0);
    }
    if (chartPeriodActive()) {
      return Number(ensureChartStats().byThemeYearCount[t.id]?.[y] || 0);
    }
    return Number(t.byYear?.[y] || 0);
  }

  function renderThemeYearChart() {
    if (!state.themesDoc?.themes) return;
    const canvas = $("#themeYearChart");
    if (!canvas) return;
    const allYears = availableThemeYears()
      .slice()
      .sort((a, b) => Number(a) - Number(b));
    const yearSet = selectedThemeYearSet();
    const years = yearSet ? allYears.filter((y) => yearSet.has(y)) : allYears;
    const series = themeYearSeriesThemes();
    const title = $("#themeYearChartTitle");
    const note = $("#themeYearChartNote");
    const focusName =
      state.themeById[state.activeTheme]?.name ||
      state.themeById[state.focusedParentId]?.name;
    const hours = metricIsHours();
    if (title) {
      title.textContent = focusName
        ? `${focusName} across years`
        : "Themes across years";
    }
    if (note) {
      const scope = chartPeriodActive()
        ? ` in ${chartPeriodLabel()}`
        : state.themeYears.length
          ? ` in ${themeYearLabel()}`
          : "";
      note.textContent = focusName
        ? `${hours ? "Hours" : "Episode counts"} for ${focusName}${scope}.`
        : hours
          ? "Top themes by hours over time — use Period above or years here to focus the lines."
          : "Top themes over time — use Period above or years here to focus the lines.";
    }
    destroyChart("themeYear");
    state.charts.themeYear = new Chart(canvas, {
      type: "line",
      data: {
        labels: years,
        datasets: series.map((t, i) => ({
          label: t.name,
          data: years.map((y) => themeYearValue(t, y)),
          borderColor: CATEGORICAL[i % CATEGORICAL.length],
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
        "Tap a parent to open child themes derived from episode content, pick years to compare eras, then filter the explorer.";
      samples.innerHTML = "";
      btn.hidden = true;
      return;
    }
    const kind = t.parentId ? "Child theme" : "Parent theme";
    const n = themeMetricInYears(t);
    const yearSuffix = state.themeYears.length ? ` in ${themeYearLabel()}` : "";
    const unit = metricIsHours() ? "hours" : "episodes";
    const ev = t.evidence || {};
    const evBits = [
      ev.transcript ? `${fmt(ev.transcript)} transcript-backed` : "",
      ev.notes ? `${fmt(ev.notes)} notes-backed` : "",
      ev.title ? `${fmt(ev.title)} title-only` : "",
    ].filter(Boolean);
    title.textContent = t.name;
    blurb.textContent = `${kind}. ${t.blurb} · ${fmtMetric(n)} ${unit}${yearSuffix}.${
      evBits.length ? ` Evidence: ${evBits.join(", ")}.` : ""
    }`;
    const samplesList = (t.samples || []).filter(sampleInThemeYears);
    samples.innerHTML = samplesList
      .map(
        (s) => `
      <div class="theme-sample">
        <strong>${escapeHtml(s.e || "")}</strong>
        <span>${escapeHtml(s.p || "Podcast")} · ${escapeHtml(s.d || "")}</span>
      </div>`
      )
      .join("") ||
      `<div class="empty">No samples${yearSuffix || " yet"}.</div>`;
    btn.hidden = false;
    btn.onclick = () => selectTheme(t.id, true);
  }

  function focusParentTheme(parentId) {
    state.focusedParentId = parentId || "";
    state.barReveal.theme = BAR_PAGE;
    state.activeTheme = parentId || "";
    state.filters.theme = parentId || "";
    if (parentId) {
      state.filters.q = "";
      if ($("#q")) $("#q").value = "";
      if ($("#topicQ")) $("#topicQ").value = "";
    }
    const sel = $("#themeFilter");
    if (sel) sel.value = parentId || "";
    state.page = 0;
    renderThemeChips();
    renderThemeChart();
    renderThemeYearChart();
    renderThemePodcastCharts();
    renderThemeDetail(parentId);
    renderEpisodeList();
  }

  function selectTheme(themeId, jumpExplore) {
    const t = state.themeById[themeId];
    if (t && !t.parentId && (t.children || []).length) {
      focusParentTheme(themeId);
      if (jumpExplore) {
        $("#explorePanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }
    if (t?.parentId) state.focusedParentId = t.parentId;
    state.activeTheme = themeId || "";
    state.filters.theme = themeId || "";
    if (themeId) {
      state.filters.q = "";
      if ($("#q")) $("#q").value = "";
      if ($("#topicQ")) $("#topicQ").value = "";
    }
    const sel = $("#themeFilter");
    if (sel) sel.value = themeId || "";
    state.page = 0;
    renderThemeChips();
    renderThemeChart();
    renderThemeYearChart();
    renderThemePodcastCharts();
    renderThemeDetail(themeId);
    renderEpisodeList();
    if (jumpExplore) {
      $("#explorePanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function runTopicSearch(raw) {
    const q = (raw || "").trim();
    $("#q").value = q;
    state.filters.q = q;
    const ql = q.toLowerCase();
    const hit = flatThemes().find(
      (t) => t.name.toLowerCase() === ql || t.id === ql
    );
    if (hit) {
      selectTheme(hit.id, true);
    } else {
      state.page = 0;
      renderEpisodeList();
      $("#explorePanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
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
        state.filters.podcast = btn.dataset.podcast;
        $("#podcastFilter").value = state.filters.podcast;
        state.page = 0;
        $("#explorePanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
        renderEpisodeList();
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
    $("#yearFilter").addEventListener("change", (e) => {
      state.filters.year = e.target.value;
      state.page = 0;
      renderEpisodeList();
    });
    $("#podcastFilter").addEventListener("change", (e) => {
      state.filters.podcast = e.target.value;
      state.page = 0;
      renderEpisodeList();
    });
    $("#themeFilter")?.addEventListener("change", (e) => {
      selectTheme(e.target.value || "", false);
    });
    $("#statusFilter").addEventListener("change", (e) => {
      state.filters.status = e.target.value;
      state.page = 0;
      renderEpisodeList();
    });
    let t;
    $("#q").addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => {
        state.filters.q = e.target.value;
        state.page = 0;
        renderEpisodeList();
      }, 160);
    });
    let topicT;
    $("#topicQ")?.addEventListener("input", (e) => {
      clearTimeout(topicT);
      topicT = setTimeout(() => runTopicSearch(e.target.value), 220);
    });
    $("#topicQ")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runTopicSearch(e.target.value);
      }
    });
    $("#clearTopic")?.addEventListener("click", () => {
      $("#topicQ").value = "";
      $("#q").value = "";
      state.filters.q = "";
      state.focusedParentId = "";
      state.themeYears = [];
      state.barReveal.theme = BAR_PAGE;
      setThemeYearPanelOpen(false);
      selectTheme("", false);
      renderThemeYearControls();
      renderThemeYearChart();
      renderThemePodcastCharts();
    });
    $("#themeYearToggle")?.addEventListener("click", (e) => {
      e.stopPropagation();
      const panel = $("#themeYearPanel");
      setThemeYearPanelOpen(!!panel?.hidden);
    });
    document.addEventListener("click", (e) => {
      const root = $("#themeYearMulti");
      if (!root || root.contains(e.target)) return;
      setThemeYearPanelOpen(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") setThemeYearPanelOpen(false);
    });
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
    $("#resetFilters").addEventListener("click", () => {
      state.filters = { year: "all", podcast: "", q: "", status: "", theme: "" };
      state.activeTheme = "";
      state.focusedParentId = "";
      state.themeYears = [];
      state.barReveal.theme = BAR_PAGE;
      state.page = 0;
      $("#yearFilter").value = "all";
      $("#podcastFilter").value = "";
      $("#statusFilter").value = "";
      if ($("#themeFilter")) $("#themeFilter").value = "";
      $("#q").value = "";
      if ($("#topicQ")) $("#topicQ").value = "";
      setThemeYearPanelOpen(false);
      applyChartPeriod({ year: "", month: "", day: "" }, { rerender: false });
      invalidateChartStats();
      rerenderCharts();
      renderHeatmap();
      renderTopTable();
      refreshThemeViews();
      renderEpisodeList();
      updatePeriodSummary();
    });

    // Nav smooth scroll
    $$("[data-jump]").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        const id = a.getAttribute("data-jump");
        document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
      });
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
      applyChartPeriod({ year: e.target.value, month: "", day: "" });
    });
    $("#periodMonth")?.addEventListener("change", (e) => {
      applyChartPeriod({
        year: state.chartPeriod.year,
        month: e.target.value,
        day: "",
      });
    });
    $("#periodDay")?.addEventListener("change", (e) => {
      applyChartPeriod({
        year: state.chartPeriod.year,
        month: state.chartPeriod.month,
        day: e.target.value,
      });
    });
    $("#periodClear")?.addEventListener("click", () => {
      applyChartPeriod({ year: "", month: "", day: "" });
    });
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
      ];
    }
    return Promise.all([
      loadJSON("tables/aggregates.json"),
      loadJSON("tables/episodes.json"),
      loadJSON("tables/podcasts.json"),
      loadJSON("tables/themes.json").catch(() => null),
      loadJSON("tables/episode-themes.json").catch(() => null),
      loadJSON("tables/notes.json").catch(() => null),
    ]);
  }

  async function init() {
    syncThemeToggle();
    state.metric = readStoredMetric();
    syncMetricToggle();
    updateMetricLabels();
    $("#bootStatus").textContent = "Loading listening history…";
    try {
      const [agg, episodes, podcasts, themesDoc, episodeThemes, notes] =
        await loadAll();
      state.agg = agg;
      state.episodes = episodes;
      state.podcasts = podcasts;
      state.themesDoc = themesDoc;
      state.episodeThemes = episodeThemes;
      state.notes = notes || {};
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

      $("#exportedAt").textContent = `Snapshot ${agg.meta.exportedAt?.slice(0, 10) || ""}`;
      renderHeroStats(agg.meta);
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
      renderDurationChart();
      renderHeatmap();
      renderTopTable();
      renderThemeYearControls();
      renderThemeChips();
      renderThemeChart();
      renderThemeYearChart();
      renderThemePodcastCharts();
      renderThemeDetail("");
      renderEpisodeList();
      wire();
      document.body.classList.add("ready");
      $("#bootStatus").textContent = "";
    } catch (err) {
      $("#bootStatus").textContent = `Failed to load: ${err.message}`;
      console.error(err);
    }
  }

  init();
})();
