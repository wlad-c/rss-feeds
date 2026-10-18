#!/usr/bin/env node
/**
 * Ship gate: fail if Listening Log chrome / Filters / sheets spill past the
 * viewport on phone widths. Agents must run this before merge/deploy of UI work.
 *
 *   node pocketcasts-history/scripts/check_mobile_edges.mjs [baseUrl]
 *
 * baseUrl defaults to http://127.0.0.1:8765 (serve pocketcasts-history/ or docs/).
 */
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

function loadPuppeteer() {
  const paths = [
    path.join(path.dirname(new URL(import.meta.url).pathname), "../../node_modules/puppeteer-core"),
    "/tmp/node_modules/puppeteer-core",
    path.join(process.cwd(), "node_modules/puppeteer-core"),
  ];
  for (const pkg of paths) {
    try {
      const req = createRequire(path.join(pkg, "package.json"));
      return req("puppeteer-core");
    } catch {
      /* try next */
    }
  }
  throw new Error(
    "puppeteer-core not found. Run: npm install puppeteer-core  (e.g. in /tmp or repo root)."
  );
}

const puppeteer = loadPuppeteer();

const base = (process.argv[2] || "http://127.0.0.1:8765").replace(/\/$/, "");
const chrome =
  process.env.CHROME_PATH ||
  ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"].find((p) =>
    fs.existsSync(p)
  ) ||
  "/usr/bin/google-chrome";

const widths = [430, 390, 320];

function spillReport(page) {
  return page.evaluate(() => {
    const iw = window.innerWidth;
    const offenders = [];
    const watch = [
      ".brand",
      ".chrome-tools",
      "#themeToggle",
      "#hardRefresh",
      "#periodBar",
      ".period-hero-show",
      ".period-hero-show .combo-input",
      "#filterSheetToggle",
      ".tab-bar",
      ".tab-item",
      "#filterSheet",
      "[data-combo-cancel]",
      "[data-combo-done]",
      ".combo-picker-chrome",
      ".filter-sheet-header",
      ".sheet-text-btn",
    ];
    for (const sel of watch) {
      for (const el of document.querySelectorAll(sel)) {
        if (el.hidden || el.closest("[hidden]")) continue;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        const overL = -r.left;
        const overR = r.right - iw;
        if (overL > 0.75 || overR > 0.75) {
          offenders.push({
            sel,
            id: el.id || "",
            overL: +overL.toFixed(1),
            overR: +overR.toFixed(1),
            L: +r.left.toFixed(1),
            R: +r.right.toFixed(1),
          });
        }
      }
    }
    return {
      iw,
      scrollW: document.documentElement.scrollWidth,
      bodySW: document.body.scrollWidth,
      edgeLock: document.documentElement.classList.contains("edge-lock"),
      offenders,
    };
  });
}

async function runWidth(browser, w) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await page.goto(`${base}/index.html`, { waitUntil: "networkidle0", timeout: 120000 });
  await page.waitForFunction(() => document.body.classList.contains("ready"), { timeout: 120000 });
  await new Promise((r) => setTimeout(r, 1200));

  // Long show title — historical overflow trigger
  await page.evaluate(() => {
    const sel = document.querySelector("#periodPodcast");
    if (!sel) return;
    const opt =
      [...sel.options].find((o) => /Rapadura|Ghibli|Milkshake/i.test(o.text)) ||
      [...sel.options].sort((a, b) => b.text.length - a.text.length)[0];
    if (opt) {
      sel.value = opt.value;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
  await new Promise((r) => setTimeout(r, 800));

  const main = await spillReport(page);

  // Open Filters sheet on compact UI
  await page.click("#filterSheetToggle");
  await new Promise((r) => setTimeout(r, 500));
  const sheet = await spillReport(page);
  await page.keyboard.press("Escape");
  await new Promise((r) => setTimeout(r, 300));

  // Open Shows picker and type in the filter field (iOS zoom trigger if <16px)
  await page.click(".period-hero-show .combo-input");
  await new Promise((r) => setTimeout(r, 500));
  const pickerFont = await page.evaluate(() => {
    const input = document.querySelector("#comboPickerInput, .combo-picker-input");
    if (!input) return { found: false };
    const cs = getComputedStyle(input);
    return {
      found: true,
      fontSizePx: parseFloat(cs.fontSize),
      fontSize: cs.fontSize,
    };
  });
  await page.focus("#comboPickerInput");
  await page.type("#comboPickerInput", "xa", { delay: 20 });
  await new Promise((r) => setTimeout(r, 300));
  const picker = await spillReport(page);
  await page.keyboard.press("Escape");
  await new Promise((r) => setTimeout(r, 400));
  const afterType = await spillReport(page);

  await page.close();
  return { w, main, sheet, picker, pickerFont, afterType };
}

function fail(label, report) {
  const pageSpill = report.scrollW > report.iw + 1 || report.bodySW > report.iw + 1;
  return pageSpill || report.offenders.length > 0;
}

const browser = await puppeteer.launch({
  headless: true,
  executablePath: chrome,
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

let failed = false;
try {
  for (const w of widths) {
    const result = await runWidth(browser, w);
    const font = result.pickerFont;
    if (!font?.found || !(font.fontSizePx >= 16)) {
      failed = true;
      console.log(
        `[FAIL] ${w}px picker-font: need ≥16px to avoid iOS focus-zoom, got ${JSON.stringify(font)}`
      );
    } else {
      console.log(`[ok] ${w}px picker-font: ${font.fontSize}`);
    }
    for (const kind of ["main", "sheet", "picker", "afterType"]) {
      const report = result[kind];
      const bad = fail(kind, report);
      const status = bad ? "FAIL" : "ok";
      console.log(
        `[${status}] ${w}px ${kind}: scrollW=${report.scrollW}/${report.iw} offenders=${report.offenders.length}`
      );
      if (bad) {
        failed = true;
        console.log(JSON.stringify(report.offenders.slice(0, 12), null, 2));
      }
    }
  }
} finally {
  await browser.close();
}

if (failed) {
  console.error("\nMobile edge check FAILED — do not merge/deploy.");
  process.exit(1);
}
console.log("\nMobile edge check passed.");
