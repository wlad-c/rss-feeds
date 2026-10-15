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
    charts: {},
    barReveal: {},
    tableReveal: { top: 12 },
    filters: { year: "all", podcast: "", q: "", status: "", theme: "" },
    page: 0,
    pageSize: 40,
    _durationStats: null,
    _localStats: null,
  };
  const BAR_PAGE = 12;

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
    }
  }

  function syncMetricToggle() {
    $$("[data-metric]").forEach((btn) => {
      const on = btn.dataset.metric === state.metric;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function updateMetricLabels() {
    const hours = metricIsHours();
    const setText = (sel, episodesText, hoursText) => {
      const el = $(sel);
      if (el) el.textContent = hours ? hoursText : episodesText;
    };
    setText("#trendLead", "Monthly episode volume with a 3-month average.", "Monthly hours of episode duration with a 3-month average.");
    setText("#cumChartTitle", "Cumulative episodes", "Cumulative hours");
    setText("#yearChartTitle", "Episodes by year", "Hours by year");
    setText("#yoyChartNote", "Compare January–December volume across years.", "Compare January–December listening hours across years.");
    setText("#topChartTitle", "Podcasts by listens", "Podcasts by hours");
    setText("#topTableMetricHead", "Eps", "Hours");
    setText("#folderChartTitle", "Folders", "Folders by hours");
    setText("#weekdayChartTitle", "Day of week (AEST/AEDT)", "Day of week by hours (AEST/AEDT)");
    setText("#hourChartTitle", "Hour of day (AEST/AEDT)", "Hour of day by hours (AEST/AEDT)");
    setText(
      "#heatmapNote",
      "Daily episode count for the last ~12 months. Darker = more listens.",
      "Daily hours of episode duration for the last ~12 months. Darker = more listening time."
    );
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
        label: "#e6edf5",
        muted: "#9aafc2",
        grid: "rgba(230,237,245,.08)",
        tooltipBg: "#0b1220",
        doughnutBorder: "#16202e",
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

  function ensureDurationStats() {
    if (state._durationStats) return state._durationStats;
    const byPodcast = Object.create(null);
    const byPodcastCount = Object.create(null);
    const byYear = Object.create(null);
    const byFolder = Object.create(null);
    const byMonth = Object.create(null);
    const byStatus = Object.create(null);
    const byDate = Object.create(null);
    const byTheme = Object.create(null);
    const byThemeYear = Object.create(null);
    const hourHours = Array.from({ length: 24 }, () => 0);
    const weekdayHours = Array.from({ length: 7 }, () => 0);
    const hourCounts = Array.from({ length: 24 }, () => 0);
    const weekdayCounts = Array.from({ length: 7 }, () => 0);
    const eps = state.episodes || [];
    for (let i = 0; i < eps.length; i++) {
      const e = eps[i];
      const h = parseDurHours(e.dur);
      const name = e.p || "Unknown";
      const year = e.y != null && e.y !== "" ? String(e.y) : "";
      const folder = e.f || "Ungrouped";
      const month = String(e.d || "").slice(0, 7);
      const status = e.st || "Unknown";
      const date = e.d || "";
      byPodcast[name] = (byPodcast[name] || 0) + h;
      byPodcastCount[name] = (byPodcastCount[name] || 0) + 1;
      if (year) byYear[year] = (byYear[year] || 0) + h;
      byFolder[folder] = (byFolder[folder] || 0) + h;
      if (month.length === 7) byMonth[month] = (byMonth[month] || 0) + h;
      byStatus[status] = (byStatus[status] || 0) + h;
      if (date) byDate[date] = (byDate[date] || 0) + h;
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
        byTheme[tid] = (byTheme[tid] || 0) + h;
        if (!year) continue;
        if (!byThemeYear[tid]) byThemeYear[tid] = Object.create(null);
        byThemeYear[tid][year] = (byThemeYear[tid][year] || 0) + h;
      }
    }
    const monthsSorted = Object.keys(byMonth).sort();
    const monthly = monthsSorted.map((month) => ({
      month,
      count: byMonth[month],
    }));
    const monthlyRolling3 = monthly.map((_, i) => {
      const slice = monthly.slice(Math.max(0, i - 2), i + 1);
      const sum = slice.reduce((acc, m) => acc + m.count, 0);
      return Math.round((sum / slice.length) * 10) / 10;
    });
    let running = 0;
    const cumulative = monthly.map((m) => {
      running += m.count;
      return { month: m.month, total: Math.round(running * 10) / 10 };
    });
    const yoyByMonth = Object.create(null);
    for (const m of monthly) {
      const [y, mo] = m.month.split("-");
      if (!yoyByMonth[mo]) yoyByMonth[mo] = Object.create(null);
      yoyByMonth[mo][y] = Math.round(m.count * 10) / 10;
    }
    state._durationStats = {
      byPodcast,
      byPodcastCount,
      byYear,
      byFolder,
      byMonth,
      byStatus,
      byDate,
      byTheme,
      byThemeYear,
      hourHours,
      weekdayHours,
      hourCounts,
      weekdayCounts,
      monthly,
      monthlyRolling3,
      cumulative,
      yoyByMonth,
    };
    return state._durationStats;
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

  function renderTrendChart() {
    const hours = metricIsHours();
    const stats = hours ? ensureDurationStats() : null;
    const monthly = hours ? stats.monthly : state.agg.monthly;
    const monthlyRolling3 = hours ? stats.monthlyRolling3 : state.agg.monthlyRolling3;
    destroyChart("trend");
    const ctx = $("#trendChart");
    state.charts.trend = new Chart(ctx, {
      type: "line",
      data: {
        labels: monthly.map((m) => m.month),
        datasets: [
          {
            label: hours ? "Hours / month" : "Episodes / month",
            data: monthly.map((m) => m.count),
            borderColor: COLORS.blue,
            backgroundColor: "rgba(0,114,178,.14)",
            fill: true,
            tension: 0.28,
            pointRadius: 0,
            borderWidth: 2.2,
          },
          {
            label: "3-month average",
            data: monthlyRolling3,
            borderColor: COLORS.amber,
            backgroundColor: "transparent",
            tension: 0.28,
            pointRadius: 0,
            borderWidth: 2.4,
            borderDash: [6, 4],
          },
        ],
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
    const series = hours ? ensureDurationStats().cumulative : state.agg.cumulative;
    destroyChart("cum");
    state.charts.cum = new Chart($("#cumChart"), {
      type: "line",
      data: {
        labels: series.map((d) => d.month),
        datasets: [
          {
            label: hours ? "Cumulative hours" : "Cumulative episodes",
            data: series.map((d) => d.total),
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
    if (!metricIsHours()) return state.agg.yearly || [];
    const byYear = ensureDurationStats().byYear;
    return Object.keys(byYear).map((year) => ({
      year: Number(year),
      count: byYear[year],
    }));
  }

  function renderYearChart() {
    renderExpandableHBar({
      key: "year",
      canvasSel: "#yearChart",
      boxSel: "#yearChartBox",
      moreSel: "#yearChartMore",
      items: yearChartItems(),
      labelOf: (d) => String(d.year),
      valueOf: (d) => d.count,
      color: COLORS.blue,
    });
  }

  function topPodcastItems() {
    if (!metricIsHours()) return state.agg.topPodcasts || [];
    const { byPodcast, byPodcastCount } = ensureDurationStats();
    return Object.keys(byPodcast).map((name) => ({
      name,
      count: byPodcastCount[name] || 0,
      hours: byPodcast[name] || 0,
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
    if (state._localStats) return state._localStats;
    const hours = metricIsHours();
    if (Array.isArray(state.episodes) && state.episodes.length) {
      const stats = ensureDurationStats();
      const hourVals = hours ? stats.hourHours : stats.hourCounts;
      const weekdayVals = hours ? stats.weekdayHours : stats.weekdayCounts;
      state._localStats = {
        hour: hourVals.map((count, h) => ({ hour: h, count })),
        weekday: weekdayVals.map((count, i) => ({
          day: WEEKDAY_NAMES[i],
          count,
        })),
      };
      return state._localStats;
    }
    state._localStats = {
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
    if (!metricIsHours()) return state.agg.folders || [];
    const byFolder = ensureDurationStats().byFolder;
    return Object.keys(byFolder).map((name) => ({ name, count: byFolder[name] }));
  }

  function statusChartItems() {
    if (!metricIsHours()) return state.agg.status || [];
    const byStatus = ensureDurationStats().byStatus;
    const order = (state.agg.status || []).map((d) => d.name);
    const names = [
      ...order.filter((n) => byStatus[n] != null),
      ...Object.keys(byStatus).filter((n) => !order.includes(n)),
    ];
    return names.map((name) => ({ name, count: byStatus[name] }));
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
    renderExpandableHBar({
      key: "dur",
      canvasSel: "#durChart",
      boxSel: "#durChartBox",
      moreSel: "#durChartMore",
      items: state.agg.avgDurationByYear || [],
      labelOf: (d) => String(d.year),
      valueOf: (d) => d.avgMinutes,
      valueLabel: "Avg minutes",
      color: COLORS.amber,
    });
  }

  function renderYoYChart() {
    const hours = metricIsHours();
    const yoy = hours ? ensureDurationStats().yoyByMonth : state.agg.yoyByMonth || {};
    const months = ["01","02","03","04","05","06","07","08","09","10","11","12"];
    const labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const years = (state.agg.meta.years || []).slice().reverse(); // oldest→newest for legend
    const dashes = [[], [6, 4], [2, 3], [8, 3, 2, 3], [], [6, 4], [2, 3], [8, 3, 2, 3]];
    destroyChart("yoy");
    state.charts.yoy = new Chart($("#yoyChart"), {
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
    const base = state.agg.heatmap || [];
    if (!metricIsHours() || !base.length) return base;
    const byDate = ensureDurationStats().byDate;
    return base.map((c) => ({
      date: c.date,
      count: Math.round((byDate[c.date] || 0) * 10) / 10,
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
    const years = selectedThemeYearSet();
    if (!years) return t.count || 0;
    let n = 0;
    for (const y of years) n += Number(t.byYear?.[y] || 0);
    return n;
  }

  function themeHoursInYears(t) {
    if (!t) return 0;
    const stats = ensureDurationStats();
    const years = selectedThemeYearSet();
    if (!years) return stats.byTheme[t.id] || 0;
    let n = 0;
    const byYear = stats.byThemeYear[t.id] || {};
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
    renderThemeDetail(state.activeTheme || state.focusedParentId || "");
    renderEpisodeList();
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
      if (themeYears) {
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
        const noteSrc = state.notes?.[String(e._i)]?.src;
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
          ${noteSrc ? `<span class="tag">${escapeHtml(noteSrc)}</span>` : ""}
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
          renderThemeChips();
          renderThemeChart();
          renderThemeYearChart();
          renderThemeDetail(state.activeTheme || state.focusedParentId || "");
          renderEpisodeList();
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
    const yearBit = state.themeYears.length
      ? ` · years ${state.themeYears
          .slice()
          .sort((a, b) => Number(a) - Number(b))
          .join(", ")}`
      : "";
    $("#themeCoverage").textContent =
      `${fmt(meta.episodesWithTheme || 0)} / ${fmt(meta.totalEpisodes || 0)} episodes carry at least one theme` +
      (meta.childCount != null
        ? ` · ${fmt(meta.parentCount)} parents / ${fmt(meta.childCount)} child themes`
        : "") +
      yearBit +
      (notesN ? ` · ${fmt(notesN)} with show notes or published transcripts` : "") +
      `. Child themes are inferred from episode content.`;
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
    const yearSuffix = state.themeYears.length ? ` · ${themeYearLabel()}` : "";
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
    if (!metricIsHours()) return Number(t.byYear?.[y] || 0);
    return Number(ensureDurationStats().byThemeYear[t.id]?.[y] || 0);
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
      note.textContent = focusName
        ? `${hours ? "Hours" : "Episode counts"} for ${focusName}${
            state.themeYears.length ? ` in ${themeYearLabel()}` : ""
          }.`
        : hours
          ? "Top themes by hours over time — select years above or drill into a parent to focus the lines."
          : "Top themes over time — select years above or drill into a parent to focus the lines.";
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
    title.textContent = t.name;
    blurb.textContent = `${kind}. ${t.blurb} · ${fmtMetric(n)} ${unit}${yearSuffix}.`;
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
      refreshThemeViews();
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
      state._durationStats = null;
      state._localStats = null;
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
