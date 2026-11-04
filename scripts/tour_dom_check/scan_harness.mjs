/* Scan DOM check (Sprint 31, ADR-060) — executes the REAL
 * static/js/scan.js against the REAL sales invoice create page
 * in jsdom and drives the whole scan flow:
 *
 *   scanner-gun path (type code + Enter) -> line filled with the
 *   product, its base unit and reference price; same code again
 *   -> quantity +1 (POS behavior); second product -> next empty
 *   line; unknown code -> inline error, form untouched;
 *   camera path (stubbed getUserMedia + BarcodeDetector emitting
 *   a code) -> feeds the SAME add path; pairing path (stubbed
 *   endpoints) -> QR renders, a polled phone result adds a line,
 *   disconnect hides the panel.
 *
 * Usage: node scan_harness.mjs <pagesDir> <staticDir>
 *
 * Harness scaffolding (real browsers provide these; jsdom does
 * not — stubs are NOT part of the product): fetch (routed to
 * canned endpoint responses built from the page's own product
 * options), navigator.mediaDevices.getUserMedia,
 * window.BarcodeDetector, HTMLMediaElement.play, and
 * window.isSecureContext (undefined in jsdom; true here because
 * the harness URL is localhost, which browsers treat as a secure
 * context — on a plain-HTTP LAN page the product code correctly
 * reports the insecure-context message instead).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { JSDOM, VirtualConsole } from "jsdom";

const [pagesDir, staticDir] = process.argv.slice(2);
if (!pagesDir || !staticDir) {
  console.error("usage: node scan_harness.mjs <pagesDir> <staticDir>");
  process.exit(2);
}
const html = readFileSync(join(pagesDir, "sales_invoice_create.scan.html"), "utf8");
const scanJs = readFileSync(join(staticDir, "js", "scan.js"), "utf8");
const qrJs = readFileSync(join(staticDir, "vendor", "qrcode-generator.js"), "utf8");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const fail = (msg) => { failures += 1; console.log(`FAIL: ${msg}`); };
const ok = (msg) => console.log(`ok: ${msg}`);
const expect = (cond, msg) => (cond ? ok(msg) : fail(msg));

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push(String(e.detail || e)));

const dom = new JSDOM(html, {
  url: "http://localhost/",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole: vc,
});
const { window } = dom;
const doc = window.document;
window.addEventListener("error", (e) => errors.push(String(e.error || e.message)));
window.HTMLElement.prototype.scrollIntoView = function () {};
window.HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
Object.defineProperty(window, "isSecureContext", { value: true });

// The page's own product options define the canned catalog.
const firstSelect = doc.querySelector('select[name$="-product"]');
const options = [...firstSelect.options].filter((o) => o.value);
if (options.length < 2) { fail("dumped page lacks two product options"); process.exit(1); }
const unitSelect = doc.querySelector('select[name$="-unit"]');
const unitOption = [...unitSelect.options].filter((o) => o.value)[0];
const catalog = {
  111: { id: options[0].value, name: "Product A", sku: "SKU-A", barcode: "111", unit_id: unitOption.value, unit_label: "Piece", sale_price: "250.00", purchase_price: "100.00" },
  222: { id: options[1].value, name: "Product B", sku: "SKU-B", barcode: "222", unit_id: unitOption.value, unit_label: "Piece", sale_price: "500.00", purchase_price: "200.00" },
};
let pairResults = [];
const jsonResp = (status, obj) => ({ ok: status >= 200 && status < 300, status, json: async () => obj });
window.fetch = async (url, opts = {}) => {
  const u = String(url);
  if (u.includes("/scan/lookup/")) {
    const code = new URLSearchParams(u.split("?")[1]).get("code");
    return catalog[code] ? jsonResp(200, catalog[code]) : jsonResp(404, { error: "not found (stub)" });
  }
  if (u.includes("/scan/sessions/") && (opts.method || "GET") === "POST" && !u.includes("revoke")) {
    return jsonResp(200, {
      session_id: "s1",
      phone_url: "http://localhost/scan/RAWTOKEN/",
      results_url: "/scan/sessions/s1/results/",
      revoke_url: "/scan/sessions/s1/revoke/",
      expires_at: "2099-01-01T00:00:00Z",
    });
  }
  if (u.includes("/results/")) return jsonResp(200, { live: true, results: pairResults });
  if (u.includes("/revoke/")) return jsonResp(200, { ok: true });
  throw new Error("unstubbed fetch: " + u);
};

// Camera stubs: a fake stream + a detector that emits "222" once.
window.navigator.mediaDevices = {
  getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
};
let detectCalls = 0;
window.BarcodeDetector = class {
  async detect() {
    detectCalls += 1;
    return detectCalls === 1 ? [{ rawValue: "222" }] : [];
  }
};

for (const src of [qrJs, scanJs]) {
  const s = doc.createElement("script");
  s.textContent = src;
  doc.body.appendChild(s);
}
await sleep(80);

const root = doc.querySelector("[data-scan-root]");
expect(!!root, "scan widget present");
const input = root.querySelector("[data-scan-input]");
const rows = () => [...doc.querySelectorAll("#line-rows > tr")];
const rowProduct = (i) => rows()[i].querySelector('select[name$="-product"]').value;
const rowQty = (i) => rows()[i].querySelector('input[name$="-quantity"]').value;
const rowPrice = (i) => rows()[i].querySelector('input[name$="-unit_price"]').value;
const flash = () => root.querySelector("[data-scan-flash]");

async function scanGun(code) {
  input.value = code;
  input.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  await sleep(30);
}

await scanGun("111");
expect(rowProduct(0) === catalog[111].id, "scan 111 filled line 1 with Product A");
expect(rowQty(0) === "1", "line 1 quantity is 1");
expect(rowPrice(0) === "250.00", "line 1 price is the reference sale price");
expect(flash().textContent.includes("Product A"), "success flash names the product");
expect(input.value === "", "input cleared for the next scan");

await scanGun("111");
expect(rowQty(0) === "2", "same code again increments quantity to 2 (POS behavior)");
expect(rows().length >= 2 && rowProduct(1) === "", "no duplicate line was created");

await scanGun("222");
expect(rowProduct(1) === catalog[222].id, "scan 222 filled line 2 with Product B");
expect(rowQty(1) === "1", "line 2 quantity is 1");

await scanGun("999");
expect(flash().classList.contains("scan-error"), "unknown code shows the inline error");
expect(rowProduct(0) === catalog[111].id && rowQty(0) === "2", "form untouched by the bad code");

// Camera path: the stubbed detector emits 222 once -> B increments.
root.querySelector("[data-scan-camera]").click();
await sleep(400);
expect(rowQty(1) === "2", "camera decode of 222 incremented Product B to 2");
const modal = root.querySelector("[data-scan-modal]");
expect(modal.hidden === false, "camera modal is open");
root.querySelector("[data-scan-modal-close]").click();
expect(modal.hidden === true, "camera modal closes");

// Pairing path: connect -> QR + link; a polled result adds a line.
root.querySelector("[data-scan-connect]").click();
await sleep(60);
const panel = root.querySelector("[data-scan-panel]");
expect(panel.hidden === false, "pairing panel opened");
expect(root.querySelector("[data-scan-qr]").innerHTML.includes("<svg"), "pairing QR rendered as SVG");
expect(root.querySelector("[data-scan-phone-link]").textContent.includes("RAWTOKEN"), "pairing link shows the one-time URL");
pairResults = [{ code: "111", product: catalog[111] }];
await sleep(2100); // one poll interval
expect(rowQty(0) === "3", "phone-scanned 111 arrived via polling and incremented line 1 to 3");
root.querySelector("[data-scan-disconnect]").click();
expect(panel.hidden === true, "disconnect hides the pairing panel");

if (errors.length) fail(`JS errors: ${errors.join(" | ")}`);
console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL SCAN DOM CHECKS PASSED");
process.exit(failures ? 1 : 0);
