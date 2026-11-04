# Tour DOM check (Sprint 31, ADR-059)

Why this exists: Sprint 30 verified the guided tour only
server-side (payload present, anchors present, engine file
served). Jason still could not activate the tour: the start
button's `hidden` attribute was defeated by the design system's
global `button,.btn{display:inline-block}` rule — author-origin
CSS beats the UA stylesheet's `[hidden]{display:none}` regardless
of specificity — so the button rendered visible on every page,
including pages with no tour, where clicking it did nothing.

This check executes the layers the server tests cannot:

1. `dump_pages.py` renders real pages (dashboard, sales invoice
   list, sales invoice create) with the populated i18n-crawl
   world, in fa and en.
2. `harness.mjs` (Node + jsdom, installed into a scratch dir —
   never vendored) loads each page with the real `app.css` and:
   - evaluates the CSS cascade for the start button's `display`
     (jsdom's own `getComputedStyle` ignores `!important` across
     rules, so the cascade is computed from the parsed rules with
     spec precedence: author !important > author normal > UA);
   - loads the real `static/js/tour.js`, asserts the engine
     reveals the button, clicks it, steps through every anchored
     step checking titles, navigates back, and closes with Esc;
   - fails on any uncaught JS exception.

Harness scaffolding (things every real browser has and jsdom
lacks — stubs live in the harness only): `scrollIntoView`,
`window.matchMedia`.

Run it: `scripts/tour_dom_check/run.sh`
