import puppeteer from 'puppeteer-core';
import fs from 'fs';

const outDir = '/opt/cursor/artifacts';
fs.mkdirSync(outDir, { recursive: true });
const report = { cases: [], fails: [] };

function pass(name, detail = {}) {
  report.cases.push({ name, ok: true, ...detail });
  console.log('PASS', name, detail.note || '');
}
function fail(name, detail = {}) {
  report.cases.push({ name, ok: false, ...detail });
  report.fails.push({ name, ...detail });
  console.log('FAIL', name, JSON.stringify(detail));
}

const browser = await puppeteer.launch({
  executablePath: '/usr/local/bin/google-chrome',
  headless: 'new',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=390,844'],
  defaultViewport: { width: 390, height: 844, deviceScaleFactor: 3 }, // iPhone-like DPR
});
const page = await browser.newPage();
await page.goto('http://127.0.0.1:8770/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction(() => document.body.classList.contains('ready'), { timeout: 120000 });

async function waitIdle() {
  await page.waitForFunction(() => !document.body.classList.contains('is-filtering'), { timeout: 20000 });
  await new Promise((r) => setTimeout(r, 150));
}

async function goThemes() {
  await page.evaluate(() => document.querySelector('[data-jump="themes"]')?.click());
  await new Promise((r) => setTimeout(r, 400));
}

async function clearTheme() {
  await page.evaluate(() => {
    const sel = document.querySelector('#periodTheme');
    if (!sel) return;
    sel.value = '';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await waitIdle();
}

async function setPodcast(nameRe) {
  await page.evaluate((re) => {
    const sel = document.querySelector('#periodPodcast');
    const opt = [...sel.options].find((o) => new RegExp(re, 'i').test(o.textContent || ''));
    if (!opt) throw new Error('podcast not found ' + re);
    sel.value = opt.value;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  }, nameRe);
  await waitIdle();
}

async function clearPodcast() {
  await page.evaluate(() => {
    const sel = document.querySelector('#periodPodcast');
    sel.value = '';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await waitIdle();
}

async function chartState() {
  return page.evaluate(() => {
    const canvas = document.querySelector('#themeChart');
    const chart = window.Chart.getChart(canvas);
    const back = document.querySelector('#themeChartBack');
    return {
      labels: chart?.data?.labels?.slice() || [],
      title: document.querySelector('#themeChartTitle')?.textContent || '',
      detail: document.querySelector('#themeDetailTitle')?.textContent || '',
      theme: document.querySelector('#periodTheme')?.value || '',
      backHidden: !!back?.hidden,
      backLabel: document.querySelector('.theme-nav-back-label')?.textContent || '',
      matchHidden: !!document.querySelector('#themeMatchPanel')?.hidden,
      matchTitle: document.querySelector('#themeMatchTitle')?.textContent || '',
    };
  });
}

async function probeScale() {
  return page.evaluate(() => {
    const canvas = document.querySelector('#themeChart');
    const chart = window.Chart.getChart(canvas);
    const y = chart.scales.y;
    const samples = [];
    const top = chart.chartArea.top;
    const bottom = chart.chartArea.bottom;
    for (let py = top; py <= bottom; py += 2) {
      const v = y.getValueForPixel(py);
      samples.push({ py, v, int: Number.isInteger(v), round: Math.round(v) });
    }
    // summarize unique (round -> count of non-int)
    const nonInt = samples.filter((s) => !s.int).length;
    const byRound = {};
    for (const s of samples) {
      byRound[s.round] = (byRound[s.round] || 0) + 1;
    }
    return { nonInt, total: samples.length, byRound, firstFew: samples.slice(0, 5), mid: samples[Math.floor(samples.length/2)] };
  });
}

async function clickRow(i, where = 'bar') {
  const t = await page.evaluate((i, where) => {
    const canvas = document.querySelector('#themeChart');
    const chart = window.Chart.getChart(canvas);
    const rect = canvas.getBoundingClientRect();
    const el = chart.getDatasetMeta(0).data[i];
    const p = el.getProps(['x', 'y', 'base'], true);
    const cssY = rect.top + (p.y / canvas.height) * rect.height;
    const cssX =
      where === 'label'
        ? rect.left + 36
        : rect.left + (((p.base + p.x) / 2) / canvas.height) * rect.height * (canvas.height / rect.height) / (canvas.width / rect.width) &&
          rect.left + ((p.base + p.x) / 2 / canvas.width) * rect.width;
    // simpler:
    const x =
      where === 'label'
        ? rect.left + 36
        : rect.left + ((p.base + p.x) / 2 / canvas.width) * rect.width;
    const y = rect.top + (p.y / canvas.height) * rect.height;
    return { label: chart.data.labels[i], x, y, raw: chart.scales.y.getValueForPixel(p.y) };
  }, i, where);
  await page.mouse.click(t.x, t.y);
  await waitIdle();
  return t;
}

async function clickBack() {
  await page.click('#themeChartBack');
  await waitIdle();
}

await goThemes();

// --- Probe scale integer behavior ---
const scaleProbe = await probeScale();
console.log('SCALE', JSON.stringify(scaleProbe));
if (scaleProbe.nonInt > 0) {
  fail('scale-returns-integers', { nonInt: scaleProbe.nonInt, total: scaleProbe.total, note: 'getValueForPixel returns floats; Number.isInteger rejects mid-row taps' });
} else {
  pass('scale-returns-integers');
}

// --- Unfiltered: click each visible parent, expect matching title/detail and child chart ---
await clearTheme();
await clearPodcast();
let parents = (await chartState()).labels;
console.log('PARENTS', parents);

// Test first 6 parents + last visible
const parentIdxs = [...new Set([0, 1, 2, 3, 4, 5, parents.length - 1])].filter((i) => i >= 0 && i < parents.length);

for (const where of ['bar', 'label']) {
  for (const i of parentIdxs) {
    await clearTheme();
    const beforeLabels = (await chartState()).labels;
    const clicked = await clickRow(i, where);
    const after = await chartState();
    const name = `parent-click[${where}][${i}] ${clicked.label}`;
    // Title should start with parent name (or be parent name · filters)
    const titleOk = after.title.startsWith(clicked.label);
    const detailOk = after.detail === clicked.label;
    const themeOk = !!after.theme;
    const drilled = after.backHidden === false;
    // Children should NOT be the same as parent list (usually); at least title/detail match
    const wrongParent = beforeLabels.some(
      (p, j) => j !== i && after.title.startsWith(p) && p !== clicked.label
    );
    if (titleOk && detailOk && drilled && !wrongParent) {
      pass(name, { theme: after.theme, children: after.labels.slice(0, 4) });
    } else {
      fail(name, { clicked: clicked.label, after, wrongParent, rawIdx: clicked.raw });
    }

    // If drilled, click first child
    if (drilled && after.labels.length) {
      const childClicked = await clickRow(0, where);
      const afterChild = await chartState();
      const cname = `child-click[${where}] after ${clicked.label} → ${childClicked.label}`;
      const childTitleOk = afterChild.title.startsWith(childClicked.label);
      const childDetailOk = afterChild.detail === childClicked.label;
      const backIsParent = afterChild.backLabel === clicked.label || afterChild.backLabel.includes(clicked.label.split(' ')[0]);
      // Chart should still show siblings (same parent children), not jump to unrelated
      const stillSiblings = afterChild.labels[0] === after.labels[0] || afterChild.labels.includes(childClicked.label);
      if (childTitleOk && childDetailOk && stillSiblings && afterChild.backHidden === false) {
        pass(cname, { theme: afterChild.theme, back: afterChild.backLabel });
      } else {
        fail(cname, { childClicked, afterChild, stillSiblings, backIsParent });
      }

      // Back from child → parent children
      await clickBack();
      const afterBack1 = await chartState();
      const b1 = `back-from-child[${where}] ${clicked.label}`;
      if (
        afterBack1.title.startsWith(clicked.label) &&
        afterBack1.backLabel === 'Themes' &&
        afterBack1.theme // parent still selected
      ) {
        pass(b1, { title: afterBack1.title, theme: afterBack1.theme });
      } else {
        fail(b1, { afterBack1 });
      }

      // Back from parent → all parents
      await clickBack();
      const afterBack2 = await chartState();
      const b2 = `back-to-parents[${where}] from ${clicked.label}`;
      if (afterBack2.backHidden === true && afterBack2.title.startsWith('Parent themes') && !afterBack2.theme) {
        pass(b2);
      } else {
        fail(b2, { afterBack2 });
      }
    }
  }
}

// --- With Australia in the World podcast filter (user's repro) ---
await clearTheme();
await setPodcast('Australia in the World');
const filteredParents = (await chartState()).labels;
console.log('FILTERED PARENTS', filteredParents);

for (const where of ['bar', 'label']) {
  for (const i of [0, 1, 2]) {
    if (i >= filteredParents.length) continue;
    await page.evaluate(() => {
      const sel = document.querySelector('#periodTheme');
      sel.value = '';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await waitIdle();
    const clicked = await clickRow(i, where);
    const after = await chartState();
    const name = `filtered-parent[${where}][${i}] ${clicked.label}`;
    if (after.title.startsWith(clicked.label) && after.detail === clicked.label) {
      pass(name, { children: after.labels.slice(0, 5) });
    } else {
      fail(name, { clicked: clicked.label, after });
      await page.screenshot({ path: `${outDir}/fail-${where}-${i}.png`, fullPage: false });
    }
  }
}

// Australian politics specifically
await page.evaluate(() => {
  const sel = document.querySelector('#periodTheme');
  sel.value = '';
  sel.dispatchEvent(new Event('change', { bubbles: true }));
});
await waitIdle();
const ausIdx = filteredParents.findIndex((l) => /australian politics/i.test(l));
if (ausIdx >= 0) {
  const clicked = await clickRow(ausIdx, 'label');
  const after = await chartState();
  const kids = after.labels;
  const looksAussie = kids.some((k) => /labor|coalition|albanese|greens|robodebt|migration/i.test(k));
  const looksUS = kids.some((k) => /trump|maga|democrats|scotus/i.test(k));
  if (after.title.startsWith('Australian politics') && looksAussie && !looksUS) {
    pass('repro-australian-politics-label', { kids });
  } else {
    fail('repro-australian-politics-label', { clicked, after, looksAussie, looksUS });
  }
  await page.screenshot({ path: `${outDir}/audit-australian.png`, fullPage: false });
} else {
  fail('repro-australian-politics-label', { note: 'Australian politics not in filtered list', filteredParents });
}

// --- Sticky theme select parent then child ---
await clearPodcast();
await clearTheme();
const selectResult = await page.evaluate(async () => {
  const sel = document.querySelector('#periodTheme');
  const parentOpt = [...sel.options].find((o) => o.value && /us-politics/.test(o.value) && !o.value.includes('--'));
  // find a child option if optgroups exist
  let parentVal = '';
  let childVal = '';
  for (const o of sel.options) {
    if (!o.value) continue;
    if (!parentVal && !o.value.includes('/')) parentVal = o.value;
  }
  // Prefer known ids
  if ([...sel.options].some((o) => o.value === 'us-politics')) parentVal = 'us-politics';
  for (const o of sel.options) {
    if (o.value && o.value !== parentVal && /trump|maga|us-/i.test(o.value + o.textContent)) {
      childVal = o.value;
      break;
    }
  }
  sel.value = parentVal;
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  return { parentVal, childVal };
});
await waitIdle();
let st = await chartState();
if (st.backHidden === false && st.theme === selectResult.parentVal) {
  pass('select-parent-drills', { theme: st.theme, title: st.title });
} else {
  fail('select-parent-drills', { selectResult, st });
}

if (selectResult.childVal) {
  await page.evaluate((v) => {
    const sel = document.querySelector('#periodTheme');
    sel.value = v;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  }, selectResult.childVal);
  await waitIdle();
  st = await chartState();
  if (st.theme === selectResult.childVal && st.backHidden === false) {
    pass('select-child-keeps-parent-context', { theme: st.theme, title: st.title, back: st.backLabel });
  } else {
    fail('select-child-keeps-parent-context', { selectResult, st });
  }
}

// --- Match panel visibility ---
await clearTheme();
st = await chartState();
if (st.matchHidden) pass('match-panel-hidden-without-theme');
else fail('match-panel-hidden-without-theme', { st });

await clickRow(0, 'bar');
st = await chartState();
if (!st.matchHidden && st.matchTitle) pass('match-panel-shown-with-theme', { matchTitle: st.matchTitle });
else fail('match-panel-shown-with-theme', { st });

// --- Rapid double-click stress: click parent 0 then immediately parent area again after render ---
await clearTheme();
await clickRow(0, 'bar');
const first = await chartState();
await clickRow(0, 'bar'); // first child of drilled view
const second = await chartState();
if (first.theme && second.detail && second.backHidden === false) {
  pass('rapid-parent-then-child', { firstTheme: first.theme, secondDetail: second.detail });
} else {
  fail('rapid-parent-then-child', { first, second });
}

// Write report
const summary = {
  total: report.cases.length,
  passed: report.cases.filter((c) => c.ok).length,
  failed: report.fails.length,
  fails: report.fails,
  scaleProbe,
};
fs.writeFileSync(`${outDir}/theme-interaction-audit.json`, JSON.stringify({ summary, cases: report.cases }, null, 2));
console.log('\nSUMMARY', JSON.stringify(summary, null, 2));
await browser.close();
process.exit(report.fails.length ? 1 : 0);
