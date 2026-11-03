/* Accountix guided tour (Sprint 30, ADR-057) — in-house, vanilla,
 * self-hosted: no library, no network, nothing external.
 *
 * The shell renders a hidden «راهنمای صفحه» button on every page and
 * a JSON payload (steps + UI strings, in the page's language) on
 * pages that have a tour. This engine reveals the button ONLY when
 * a payload exists and at least one step's anchor is present, so a
 * page without a tour — or a browser without JS — never shows a
 * dead control. Steps whose anchor is absent at runtime
 * (role-dependent UI, empty tables) are skipped silently.
 */
(function () {
  "use strict";

  function onReady(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  function anchorEl(anchor) {
    return document.querySelector('[data-tour="' + anchor + '"]');
  }

  onReady(function () {
    var dataEl = document.getElementById("tour-data");
    var startBtn = document.querySelector("[data-tour-start]");
    if (!dataEl || !startBtn) return;
    var payload;
    try {
      payload = JSON.parse(dataEl.textContent);
    } catch (err) {
      return;
    }
    if (!payload || !Array.isArray(payload.steps)) return;
    var steps = payload.steps.filter(function (s) {
      return s && s.anchor && anchorEl(s.anchor);
    });
    if (!steps.length) return;
    startBtn.hidden = false;
    startBtn.addEventListener("click", function () {
      startTour(steps, payload.ui || {}, startBtn);
    });
  });

  function startTour(allSteps, ui, startBtn) {
    var rtl = document.documentElement.dir === "rtl";
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var root = document.createElement("div");
    root.className = "tour-root";
    root.innerHTML =
      '<div class="tour-spot"></div>' +
      '<div class="tour-card" role="dialog" aria-live="polite">' +
      '<p class="tour-counter"></p>' +
      '<h3 class="tour-title"></h3>' +
      '<p class="tour-body"></p>' +
      '<div class="tour-nav">' +
      '<button type="button" class="btn btn-ghost tour-prev"></button>' +
      '<button type="button" class="btn btn-ghost tour-close"></button>' +
      '<button type="button" class="btn tour-next"></button>' +
      "</div></div>";
    document.body.appendChild(root);
    var spot = root.querySelector(".tour-spot");
    var card = root.querySelector(".tour-card");
    var counter = root.querySelector(".tour-counter");
    var title = root.querySelector(".tour-title");
    var body = root.querySelector(".tour-body");
    var prevBtn = root.querySelector(".tour-prev");
    var nextBtn = root.querySelector(".tour-next");
    var closeBtn = root.querySelector(".tour-close");
    prevBtn.textContent = ui.prev || "";
    closeBtn.textContent = ui.close || "";

    var steps = allSteps.slice();
    var idx = -1;
    var currentEl = null;
    var rafId = null;

    function end() {
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position);
      if (rafId) cancelAnimationFrame(rafId);
      root.remove();
      if (startBtn) startBtn.focus();
    }

    function position() {
      if (!currentEl) return;
      var r = currentEl.getBoundingClientRect();
      var pad = 6;
      spot.style.left = r.left - pad + "px";
      spot.style.top = r.top - pad + "px";
      spot.style.width = r.width + pad * 2 + "px";
      spot.style.height = r.height + pad * 2 + "px";
      // Card: below the target when it fits, above otherwise;
      // horizontally clamped to the viewport.
      var cardW = Math.min(330, window.innerWidth - 16);
      var cardH = card.offsetHeight || 170;
      var top = r.bottom + pad + 10;
      if (top + cardH > window.innerHeight - 8) {
        top = Math.max(8, r.top - pad - 10 - cardH);
      }
      var left = Math.min(Math.max(8, r.left), window.innerWidth - cardW - 8);
      card.style.top = top + "px";
      card.style.left = left + "px";
      card.style.width = cardW + "px";
    }

    function track() {
      // Keep the spotlight glued while a smooth scroll settles.
      var started = Date.now();
      (function frame() {
        position();
        if (Date.now() - started < 450) rafId = requestAnimationFrame(frame);
      })();
    }

    function show(i, direction) {
      // Skip steps whose anchor vanished since the tour started.
      while (i >= 0 && i < steps.length && !anchorEl(steps[i].anchor)) {
        i += direction || 1;
      }
      if (i < 0 || i >= steps.length) {
        end();
        return;
      }
      idx = i;
      currentEl = anchorEl(steps[i].anchor);
      title.textContent = steps[i].title || "";
      body.textContent = steps[i].body || "";
      counter.textContent = (ui.counter || "{i}/{n}")
        .replace("{i}", String(idx + 1))
        .replace("{n}", String(steps.length));
      prevBtn.style.visibility = idx === 0 ? "hidden" : "visible";
      nextBtn.textContent = idx === steps.length - 1 ? ui.finish || "" : ui.next || "";
      currentEl.scrollIntoView({
        block: "center",
        behavior: reduced ? "auto" : "smooth",
      });
      position();
      track();
      nextBtn.focus();
    }

    function next() {
      show(idx + 1, 1);
    }
    function prev() {
      show(idx - 1, -1);
    }

    function onKey(ev) {
      if (ev.key === "Escape") {
        ev.preventDefault();
        end();
      } else if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        if (rtl) next();
        else prev();
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        if (rtl) prev();
        else next();
      }
    }

    nextBtn.addEventListener("click", next);
    prevBtn.addEventListener("click", prev);
    closeBtn.addEventListener("click", end);
    root.addEventListener("click", function (ev) {
      if (ev.target === root || ev.target === spot) end();
    });
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, { passive: true });

    show(0, 1);
  }
})();
