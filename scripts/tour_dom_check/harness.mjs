/* Tour DOM check (Sprint 31, ADR-059) — executes the REAL
 * static/js/tour.js against REAL rendered pages in jsdom and
 * click-drives the whole tour. Sprint 30 verified the tour only
 * server-side; Jason still could not activate it, so this harness
 * exists to exercise the exact layers the server tests cannot:
 * the CSS cascade (is the hidden start button really hidden?),
 * the engine's reveal logic, and full step navigation.
 *
 * Usage: node harness.mjs <pagesDir> <staticDir>
 * Exit code 0 = every page passed; 1 = failures (printed).
 *
 * Harness scaffolding (things every real browser provides
 * natively and jsdom lacks — stubs are NOT part of the product):
 *   - Element.scrollIntoView (jsdom has no layout engine)
 *   - window.matchMedia (jsdom@24 does not implement it; tour.js
 *     queries prefers-reduced-motion through it)
 * Everything else — getBoundingClientRect zeros,
 * requestAnimationFrame (pretendToBeVisual) — is jsdom's own.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { JSDOM, VirtualConsole } from "jsdom";

const [pagesDir, staticDir] = process.argv.slice(2);
if (!pagesDir || !staticDir) {
  console.error("usage: node harness.mjs <pagesDir> <staticDir>");
  process.exit(2);
}
const tourJs = readFileSync(join(staticDir, "js", "tour.js"), "utf8");
const appCss = readFileSync(join(staticDir, "css", "app.css"), "utf8");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const fail = (page, msg) => {
  failures += 1;
  console.log(`FAIL ${page}: ${msg}`);
};
const ok = (page, msg) => console.log(`ok   ${page}: ${msg}`);

function makeDom(html, { withCss = false, withTour = false } = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.detail || e)));
  vc.on("error", (m) => errors.push(String(m)));
  let doc = html.replace(/<link[^>]*app\.css[^>]*>/, "");
  if (withCss) doc = doc.replace("</head>", `<style>${appCss}</style></head>`);
  const dom = new JSDOM(doc, {
    url: "http://localhost/",
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  const { window } = dom;
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.matchMedia =
    window.matchMedia ||
    ((query) => ({
      matches: false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
  window.addEventListener("error", (e) => errors.push(String(e.error || e.message)));
  if (withTour) {
    const s = window.document.createElement("script");
    s.textContent = tourJs;
    window.document.body.appendChild(s);
  }
  return { dom, window, errors };
}

for (const file of readdirSync(pagesDir).filter((f) => f.endsWith(".html")).sort()) {
  const html = readFileSync(join(pagesDir, file), "utf8");

  // --- Phase 1: CSS contract — the start button ships `hidden`;
  // the author stylesheet must not defeat it (the Sprint 31 bug:
  // `button,.btn{display:inline-block}` overrides the UA
  // `[hidden]{display:none}` rule in every real browser).
  // jsdom's own getComputedStyle cascade ignores !important
  // across rules (a known jsdom gap), so the cascade for the
  // `display` property is evaluated HERE, over the real parsed
  // stylesheet, with the spec's precedence for this element:
  // author !important > author normal > UA normal ([hidden]).
  {
    const { window } = makeDom(html, { withCss: true });
    const btn = window.document.querySelector("[data-tour-start]");
    if (!btn) { fail(file, "start button missing from markup"); continue; }
    if (!btn.hidden) fail(file, "start button lacks the hidden attribute in markup");
    const spec = (sel) => {
      // (ids, classes+attrs+pseudos, elements) for one selector.
      const a = (sel.match(/#/g) || []).length;
      const b = (sel.match(/\.|\[|:(?!:)/g) || []).length;
      const c = (sel.replace(/#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[\w-]+(\([^)]*\))?/g, " ").match(/[a-zA-Z][\w-]*/g) || []).length;
      return [a, b, c];
    };
    const candidates = [
      { display: "none", origin: 0, important: false, spec: [0, 1, 0], order: -1, from: "UA [hidden]" },
    ];
    let order = 0;
    for (const rule of window.document.styleSheets[0].cssRules) {
      order += 1;
      if (!rule.selectorText || !rule.style) continue;
      const disp = rule.style.getPropertyValue("display");
      if (!disp) continue;
      for (const sel of rule.selectorText.split(",")) {
        const s = sel.trim();
        let matches = false;
        try { matches = btn.matches(s); } catch { matches = false; }
        if (matches)
          candidates.push({
            display: disp,
            origin: 1,
            important: rule.style.getPropertyPriority("display") === "important",
            spec: spec(s),
            order,
            from: s,
          });
      }
    }
    const key = (c) => [c.origin + (c.important ? 2 : 0), ...c.spec, c.order];
    candidates.sort((x, y) => {
      const kx = key(x), ky = key(y);
      for (let i = 0; i < kx.length; i++) if (kx[i] !== ky[i]) return kx[i] - ky[i];
      return 0;
    });
    const winner = candidates[candidates.length - 1];
    if (winner.display !== "none")
      fail(file, `CSS cascade: hidden button's display resolves to ${winner.display} (from ${winner.from}), must be none`);
    else ok(file, `CSS cascade: hidden button display:none (winner: ${winner.from})`);
    window.close();
  }

  // --- Phase 2: engine contract — reveal, click, step through.
  const { window, errors } = makeDom(html, { withTour: true });
  const doc = window.document;
  await sleep(120);
  const btn = doc.querySelector("[data-tour-start]");
  const payloadEl = doc.getElementById("tour-data");
  if (!payloadEl) { fail(file, "tour payload missing"); window.close(); continue; }
  const payload = JSON.parse(payloadEl.textContent);
  const anchored = payload.steps.filter((s) => doc.querySelector(`[data-tour="${s.anchor}"]`));
  if (btn.hidden) { fail(file, "engine did NOT reveal the start button"); window.close(); continue; }
  ok(file, `engine revealed start button (${anchored.length}/${payload.steps.length} steps anchored)`);

  btn.click();
  await sleep(30);
  const root = doc.querySelector(".tour-root");
  if (!root) { fail(file, "clicking the start button opened no tour"); window.close(); continue; }
  const title = () => doc.querySelector(".tour-title")?.textContent;
  const counter = () => doc.querySelector(".tour-counter")?.textContent;
  if (title() !== anchored[0].title)
    fail(file, `step 1 title ${JSON.stringify(title())} != ${JSON.stringify(anchored[0].title)}`);
  let seen = 1;
  for (let i = 1; i < anchored.length; i++) {
    doc.querySelector(".tour-next").click();
    await sleep(10);
    if (!doc.querySelector(".tour-root")) { fail(file, `tour closed early at step ${i + 1}`); break; }
    if (title() !== anchored[i].title)
      fail(file, `step ${i + 1} title ${JSON.stringify(title())} != ${JSON.stringify(anchored[i].title)}`);
    seen += 1;
  }
  if (seen === anchored.length) ok(file, `stepped through all ${seen} steps; counter ends at ${JSON.stringify(counter())}`);
  // prev navigation
  if (anchored.length > 1) {
    doc.querySelector(".tour-prev").click();
    await sleep(10);
    if (title() !== anchored[anchored.length - 2].title)
      fail(file, "prev did not return to the previous step");
    else ok(file, "prev navigation works");
  }
  // Esc closes
  doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await sleep(10);
  if (doc.querySelector(".tour-root")) fail(file, "Esc did not close the tour");
  else ok(file, "Esc closes the tour");
  if (errors.length) fail(file, `JS errors: ${errors.join(" | ")}`);
  window.close();
}

console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL DOM CHECKS PASSED");
process.exit(failures ? 1 : 0);
