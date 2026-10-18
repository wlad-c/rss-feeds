#!/usr/bin/env node
/**
 * Ship gate: filter comboboxes must open usable lists on desktop/iPad widths
 * and the full-screen picker on compact widths. Catches overflow-clipped
 * dropdowns (empty / 1–2 row blue strip) before merge/deploy.
 *
 *   node pocketcasts-history/scripts/check_filter_combos.mjs [baseUrl]
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

const DESKTOP = [
  [1180, 820],
  [1024, 768],
  [900, 700],
  [861, 700],
];
const MOBILE = [
  [430, 844],
  [390, 844],
];

const COMBOS = [
  {
    name: "show",
    input: "#periodPodcastInput",
    list: "#periodPodcast-list",
    select: "#periodPodcast",
    minOptions: 20,
    typeQuery: "xadrez",
    expectMatch: /xadrez/i,
  },
  {
    name: "country",
    input: "#periodCountryInput",
    list: "#periodCountry-list",
    select: "#periodCountry",
    minOptions: 3,
    ensureVisible: true,
  },
  {
    name: "theme",
    input: "#periodThemeInput",
    list: "#periodTheme-list",
    select: "#periodTheme",
    minOptions: 10,
    ensureVisible: true,
    typeQuery: "diplom",
    expectMatch: /diplom/i,
  },
];

function listReport(page, { input, list }) {
  return page.evaluate(
    ({ inputSel, listSel }) => {
      const inputEl = document.querySelector(inputSel);
      const listEl = document.querySelector(listSel);
      const picker = document.querySelector("#comboPickerHost");
      const ir = inputEl?.getBoundingClientRect();
      const lr = listEl?.getBoundingClientRect();
      const options = listEl ? [...listEl.querySelectorAll(".combo-option")] : [];
      const visibleOpts = options.filter((o) => {
        const b = o.getBoundingClientRect();
        return b.width > 4 && b.height > 4 && b.bottom > 0 && b.top < window.innerHeight;
      });
      const clippedByAncestor = (() => {
        if (!listEl || listEl.hidden) return false;
        // Unfiltered desktop lists should be a real panel, not a 1–2 row stub.
        return (lr?.height || 0) < 80 || (lr?.width || 0) < 120;
      })();
      return {
        compact: window.matchMedia("(max-width: 860px)").matches,
        inputFound: !!inputEl,
        listFound: !!listEl,
        listHidden: !!listEl?.hidden,
        listParent: listEl?.parentElement?.tagName || null,
        ported: !!listEl?.classList.contains("is-ported"),
        pickerOpen: !!(picker && !picker.hidden),
        inputW: ir ? +ir.width.toFixed(1) : 0,
        listW: lr ? +lr.width.toFixed(1) : 0,
        listH: lr ? +lr.height.toFixed(1) : 0,
        listTop: lr ? +lr.top.toFixed(1) : 0,
        optionCount: options.length,
        visibleOptions: visibleOpts.length,
        firstVisible: visibleOpts.slice(0, 5).map((o) => o.textContent.trim()),
        clippedByAncestor,
        filtersExpanded: document.body.classList.contains("filters-expanded"),
      };
    },
    { inputSel: input, listSel: list }
  );
}

async function ensureFacetVisible(page, inputSel) {
  const need = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return "missing";
    if (el.closest(".is-overflow-hidden")) return "overflow";
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return "tiny";
    return "ok";
  }, inputSel);
  if (need === "ok") return;
  if (need === "missing") throw new Error(`Missing input ${inputSel}`);
  await page.click("#filterSheetToggle");
  await new Promise((r) => setTimeout(r, 450));
}

async function openDesktopCombo(page, combo) {
  if (combo.ensureVisible) await ensureFacetVisible(page, combo.input);
  await page.click(combo.input);
  await new Promise((r) => setTimeout(r, 350));
  return listReport(page, combo);
}

async function closeOpenUi(page) {
  await page.keyboard.press("Escape");
  await page.evaluate(() => {
    document.activeElement?.blur?.();
    document.querySelector("#comboPickerHost")?.setAttribute("hidden", "");
    document.body.classList.remove("combo-picker-open");
    document.querySelectorAll(".combo-list").forEach((el) => {
      el.hidden = true;
      el.classList.remove("is-ported");
    });
  });
  await new Promise((r) => setTimeout(r, 200));
}

function failDesktop(report, combo, { typed = false } = {}) {
  const reasons = [];
  const minOpts = typed ? 1 : combo.minOptions;
  const minVisible = typed ? 1 : Math.min(3, combo.minOptions);
  // Empty/filtered lists shrink to content; only demand a tall panel when many rows exist.
  const minHeight = report.optionCount >= 4 ? 100 : 40;
  if (report.compact) reasons.push("expected desktop (non-compact) layout");
  if (report.pickerOpen) reasons.push("mobile picker opened on desktop width");
  if (report.listHidden) reasons.push("list stayed hidden");
  if (!report.ported && report.listParent !== "BODY") {
    reasons.push(`list not portaled to body (parent=${report.listParent})`);
  }
  if (report.listH < minHeight) reasons.push(`list height ${report.listH}px < ${minHeight}`);
  if (report.listW < Math.min(160, report.inputW * 0.85)) {
    reasons.push(`list width ${report.listW}px too narrow vs input ${report.inputW}px`);
  }
  if (report.visibleOptions < minVisible) {
    reasons.push(`only ${report.visibleOptions} visible options`);
  }
  if (report.optionCount < minOpts) {
    reasons.push(`optionCount ${report.optionCount} < ${minOpts}`);
  }
  // "Clipped" only when we expected a tall multi-row panel.
  if (!typed && report.optionCount >= 4 && report.clippedByAncestor) {
    reasons.push("list box looks clipped/tiny");
  }
  return reasons;
}

function failMobile(report) {
  const reasons = [];
  if (!report.compact) reasons.push("expected compact layout");
  if (!report.pickerOpen) reasons.push("mobile picker did not open");
  return reasons;
}

const browser = await puppeteer.launch({
  headless: true,
  executablePath: chrome,
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

let failed = false;
try {
  for (const [w, h] of DESKTOP) {
    const page = await browser.newPage();
    await page.setViewport({ width: w, height: h, deviceScaleFactor: 2, isMobile: false, hasTouch: true });
    await page.goto(`${base}/index.html`, { waitUntil: "networkidle0", timeout: 120000 });
    await page.waitForFunction(() => document.body.classList.contains("ready"), { timeout: 120000 });
    await new Promise((r) => setTimeout(r, 700));

    for (const combo of COMBOS) {
      await closeOpenUi(page);
      const report = await openDesktopCombo(page, combo);
      const reasons = failDesktop(report, combo);
      const status = reasons.length ? "FAIL" : "ok";
      if (reasons.length) failed = true;
      console.log(
        `[${status}] ${w}x${h} desktop ${combo.name}: list ${report.listW}x${report.listH} opts=${report.optionCount} visible=${report.visibleOptions} ported=${report.ported}`
      );
      if (reasons.length) console.log("  ", reasons.join("; "), JSON.stringify(report.firstVisible));

      if (combo.typeQuery && !reasons.length) {
        await page.click(combo.input, { clickCount: 3 });
        await page.type(combo.input, combo.typeQuery, { delay: 15 });
        await new Promise((r) => setTimeout(r, 300));
        const typed = await listReport(page, combo);
        const typeReasons = failDesktop(typed, combo, { typed: true });
        const labels = typed.firstVisible.join(" | ");
        if (combo.expectMatch && typed.optionCount >= 1 && !combo.expectMatch.test(labels)) {
          typeReasons.push(`type "${combo.typeQuery}" produced no matching labels (${labels})`);
        }
        if (typed.optionCount < 1) typeReasons.push("type-filter emptied the list incorrectly");
        const tStatus = typeReasons.length ? "FAIL" : "ok";
        if (typeReasons.length) failed = true;
        console.log(
          `[${tStatus}] ${w}x${h} desktop ${combo.name} type="${combo.typeQuery}": opts=${typed.optionCount} visible=${typed.visibleOptions}`
        );
        if (typeReasons.length) console.log("  ", typeReasons.join("; "));
      }

      // Pick first real option and ensure select updates (show only once per width)
      if (combo.name === "show" && !reasons.length) {
        const before = await page.$eval(combo.select, (el) => el.value);
        await page.evaluate((listSel) => {
          const opt = [...document.querySelectorAll(`${listSel} .combo-option`)].find(
            (o) => o.getAttribute("data-value")
          );
          opt?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        }, combo.list);
        await new Promise((r) => setTimeout(r, 250));
        const after = await page.$eval(combo.select, (el) => el.value);
        const closed = await page.$eval(combo.list, (el) => el.hidden);
        if (!after || after === before && before !== "") {
          // empty → some show is fine; require change from ""
        }
        if (!closed) {
          failed = true;
          console.log(`[FAIL] ${w}x${h} desktop show pick: list stayed open`);
        } else if (!after) {
          failed = true;
          console.log(`[FAIL] ${w}x${h} desktop show pick: select value empty after pick`);
        } else {
          console.log(`[ok] ${w}x${h} desktop show pick: value=${JSON.stringify(after)}`);
        }
      }
    }
    await page.close();
  }

  for (const [w, h] of MOBILE) {
    const page = await browser.newPage();
    await page.setViewport({
      width: w,
      height: h,
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
    });
    await page.goto(`${base}/index.html`, { waitUntil: "networkidle0", timeout: 120000 });
    await page.waitForFunction(() => document.body.classList.contains("ready"), { timeout: 120000 });
    await new Promise((r) => setTimeout(r, 700));
    await page.click("#periodPodcastInput");
    await new Promise((r) => setTimeout(r, 400));
    const report = await listReport(page, COMBOS[0]);
    // On mobile, inspect picker list instead
    const pickerInfo = await page.evaluate(() => {
      const host = document.querySelector("#comboPickerHost");
      const input = document.querySelector("#comboPickerInput");
      const opts = [...document.querySelectorAll(".combo-picker-list .combo-option")];
      const visible = opts.filter((o) => {
        const b = o.getBoundingClientRect();
        return b.width > 4 && b.height > 4;
      });
      return {
        open: !!(host && !host.hidden),
        fontSize: input ? parseFloat(getComputedStyle(input).fontSize) : 0,
        optionCount: opts.length,
        visibleOptions: visible.length,
      };
    });
    const reasons = failMobile(report);
    if (!pickerInfo.open) reasons.push("picker host hidden");
    if (pickerInfo.fontSize < 16) reasons.push(`picker font ${pickerInfo.fontSize}px < 16`);
    if (pickerInfo.visibleOptions < 5) reasons.push(`picker visible opts ${pickerInfo.visibleOptions}`);
    const status = reasons.length ? "FAIL" : "ok";
    if (reasons.length) failed = true;
    console.log(
      `[${status}] ${w}x${h} mobile show picker: font=${pickerInfo.fontSize}px opts=${pickerInfo.optionCount} visible=${pickerInfo.visibleOptions}`
    );
    if (reasons.length) console.log("  ", reasons.join("; "));
    await page.close();
  }
} finally {
  await browser.close();
}

if (failed) {
  console.error("\nFilter combo check FAILED — do not merge/deploy.");
  process.exit(1);
}
console.log("\nFilter combo check passed.");
