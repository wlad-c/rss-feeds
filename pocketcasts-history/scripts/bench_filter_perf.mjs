#!/usr/bin/env node
/** Quick hot-path bench for filter matching / stats (no DOM). */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const episodes = JSON.parse(fs.readFileSync(path.join(root, "tables/episodes.json"), "utf8"));
const episodeThemes = JSON.parse(fs.readFileSync(path.join(root, "tables/episode-themes.json"), "utf8"));
const notes = JSON.parse(fs.readFileSync(path.join(root, "tables/notes.json"), "utf8"));
const countries = JSON.parse(fs.readFileSync(path.join(root, "tables/podcast-countries.json"), "utf8"));
const themesDoc = JSON.parse(fs.readFileSync(path.join(root, "tables/themes.json"), "utf8"));

const byId = {};
for (const t of themesDoc.themes || []) {
  byId[t.id] = t;
  for (const c of t.children || []) byId[c.id] = c;
}

function parseDurHours(dur) {
  if (!dur) return 0;
  const parts = String(dur).split(":").map(Number);
  if (!parts.length || parts.some((n) => !Number.isFinite(n))) return 0;
  let sec = 0;
  if (parts.length === 3) sec = parts[0] * 3600 + parts[1] * 60 + parts[2];
  else if (parts.length === 2) sec = parts[0] * 60 + parts[1];
  else sec = parts[0];
  return sec > 0 ? sec / 3600 : 0;
}

function countryFor(e) {
  return countries.byPodcast?.[e.p] || countries.byAuthor?.[e.a] || "Unknown";
}

const LISTEN_TZ = "Australia/Sydney";
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

function time(label, fn) {
  const t0 = performance.now();
  const v = fn();
  const ms = performance.now() - t0;
  console.log(`${label}: ${ms.toFixed(1)}ms`);
  return { ms, v };
}

const period = { year: "2024", month: "", day: "", country: "", podcast: "", theme: "", status: "", q: "" };

time("OLD match+haystack scan (year=2024)", () => {
  let n = 0;
  for (let i = 0; i < episodes.length; i++) {
    const e = episodes[i];
    if (String(e.y) !== "2024") continue;
    const th = episodeThemes[i] || [];
    const themeNames = th.map((id) => byId[id]?.name || id).join(" ");
    const note = notes[String(i)]?.text || "";
    const hay = `${e.e || ""} ${e.p || ""} ${e.a || ""} ${e.f || ""} ${countryFor(e)} ${themeNames} ${note}`.toLowerCase();
    if (hay.includes("zzzzz-nope")) continue;
    parseDurHours(e.dur);
    const d = parseListenUtc(e.t);
    if (d) sydneyHourAndWeekday(d);
    n++;
  }
  return n;
});

const idx = time("NEW prepare index", () => {
  const n = episodes.length;
  const hours = new Float64Array(n);
  const countriesArr = new Array(n);
  const hays = new Array(n);
  const hourOfDay = new Int8Array(n);
  const weekday = new Int8Array(n);
  hourOfDay.fill(-1);
  weekday.fill(-1);
  for (let i = 0; i < n; i++) {
    const e = episodes[i];
    hours[i] = parseDurHours(e.dur);
    const c = countryFor(e);
    countriesArr[i] = c;
    const th = episodeThemes[i] || [];
    const themeNames = th.map((id) => byId[id]?.name || id).join(" ");
    const note = notes[String(i)]?.text || "";
    hays[i] = `${e.e || ""} ${e.p || ""} ${e.a || ""} ${e.f || ""} ${c} ${themeNames} ${note}`.toLowerCase();
    const d = parseListenUtc(e.t);
    if (d) {
      const loc = sydneyHourAndWeekday(d);
      if (loc.hour != null) hourOfDay[i] = loc.hour;
      if (loc.weekday != null) weekday[i] = loc.weekday;
    }
  }
  return { hours, countriesArr, hays, hourOfDay, weekday };
}).v;

time("NEW indexed match scan (year=2024)", () => {
  let n = 0;
  for (let i = 0; i < episodes.length; i++) {
    const e = episodes[i];
    if (String(e.y) !== period.year) continue;
    if (idx.hays[i].includes("zzzzz-nope")) continue;
    const h = idx.hours[i];
    const hr = idx.hourOfDay[i];
    const wd = idx.weekday[i];
    n += h + (hr >= 0 ? 1 : 0) + (wd >= 0 ? 1 : 0);
  }
  return n;
});

time("NEW search scan q=labor (prebuilt hay)", () => {
  const qq = "labor";
  let n = 0;
  for (let i = 0; i < episodes.length; i++) {
    if (idx.hays[i].includes(qq)) n++;
  }
  return n;
});

time("OLD search scan q=labor (rebuild hay)", () => {
  const qq = "labor";
  let n = 0;
  for (let i = 0; i < episodes.length; i++) {
    const e = episodes[i];
    const th = episodeThemes[i] || [];
    const themeNames = th.map((id) => byId[id]?.name || id).join(" ");
    const note = notes[String(i)]?.text || "";
    const hay = `${e.e || ""} ${e.p || ""} ${e.a || ""} ${e.f || ""} ${countryFor(e)} ${themeNames} ${note}`.toLowerCase();
    if (hay.includes(qq)) n++;
  }
  return n;
});
