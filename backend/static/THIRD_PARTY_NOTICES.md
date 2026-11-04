# Third-Party Notices — self-hosted web assets

Sprint 28 (ADR-053). Accountix is offline-first: every font and icon
the UI uses is vendored into `backend/static/` from its official
upstream release and served by the app itself. Nothing is fetched
from a CDN or any external host at runtime.

## Fonts (woff2, `static/fonts/`)

One combined CSS stack — `"Inter", "Vazirmatn", …` — gives Latin
glyphs to Inter and Persian glyphs to Vazirmatn by per-character
fallback in both locales.

### Vazirmatn 33.003 — Persian

- Source: https://github.com/rastikerdar/vazirmatn/releases/tag/v33.003
  (release archive `vazirmatn-v33.003.zip`,
  sha256 `0a9afd41967e6f57096a56a181a23f81a2b999b62f1f2a4e4b26736580854fdb`)
- License: SIL Open Font License 1.1 — full text in
  `fonts/OFL-Vazirmatn.txt`.
- Files (upstream `fonts/webfonts/Vazirmatn-<Weight>.woff2`):

| Local file | Weight | Bytes | sha256 |
|---|---|---|---|
| `fonts/vazirmatn-400.woff2` | 400 (Regular) | 50684 | `e382101336c6eb32cfb31381c027d02d2e0354bad08f6a395d4088beb3db3d91` |
| `fonts/vazirmatn-500.woff2` | 500 (Medium) | 51128 | `3333e31188a2b628db8780ca22fd5aad85bc083ccee9beb8d4d52db18cb98d48` |
| `fonts/vazirmatn-700.woff2` | 700 (Bold) | 51020 | `836fae7d42d83faa249bc00e0099592be98a1fa260d22d82f269b6091e585627` |
| `fonts/vazirmatn-800.woff2` | 800 (ExtraBold) | 51120 | `cd67558bbca0ad319b89e3b2edb8a914f87f864951d7a9d24e1404cbf3b45b02` |

### Inter 4.1 — Latin

- Source: https://github.com/rsms/inter/releases/tag/v4.1
  (release archive `Inter-4.1.zip`,
  sha256 `9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`)
- License: SIL Open Font License 1.1 — full text in
  `fonts/OFL-Inter.txt`.
- Files (upstream `web/Inter-<Weight>.woff2`):

| Local file | Weight | Bytes | sha256 |
|---|---|---|---|
| `fonts/inter-400.woff2` | 400 (Regular) | 111268 | `e06f6b1bc553aaea4e4668023ed0ab0a147129c3107f511bc7d03d361b0ae085` |
| `fonts/inter-500.woff2` | 500 (Medium) | 114348 | `0ff3e94614e1493eb556314fd247ae6c4a85a7783b4cc86be539940cf83f2a48` |
| `fonts/inter-700.woff2` | 700 (Bold) | 114840 | `fa888127b6da015b65569f0351f3b5c391ad928904951f1c20e9f8462a8d95ea` |
| `fonts/inter-800.woff2` | 800 (ExtraBold) | 114856 | `6f75025856f8db1b2186e9cb89be9de9894932c8b7b20f4df5e65916ff714e34` |

Total font payload: **659,264 bytes** (8 files).

## Icons (SVG sprite, `static/icons.svg`)

- Source: Lucide **1.67.0** —
  https://github.com/lucide-icons/lucide/releases/tag/1.67.0
  (release archive `lucide-icons-1.67.0.zip`,
  sha256 `035253db719965b1eee4877f4fb675a695822181a21d06caae60b9d9c0ec4e66`)
- License: ISC — full text in `icons-LICENSE.txt`.
- The sprite (36 symbols, one `<symbol id="i-<name>">` per icon) is
  generated from the release's `icons/*.svg` files by
  `scripts/build_icon_sprite.py`; regenerate with:

  ```bash
  python3 scripts/build_icon_sprite.py /path/to/lucide-1.67.0/icons
  ```

## JavaScript libraries (Sprint 31, ADR-060 — `static/vendor/`)

Vendored for barcode/QR scanning in invoicing. Same rule as the
fonts: official upstream files, self-hosted, nothing fetched at
runtime. The zero-external test scopes these files to
fetch-capable patterns (see ADR-060): their comment blocks carry
attribution URLs and `qrcode-generator.js` embeds the SVG `xmlns`
namespace identifier — inert strings, never requests.

### jsQR 1.4.0 — QR decoding fallback

- Source: https://github.com/cozmo/jsQR (npm `jsqr@1.4.0`,
  `dist/jsQR.js` verbatim)
- License: Apache-2.0 — full text in `vendor/jsQR-LICENSE.txt`.

| Local file | Bytes | sha256 |
|---|---|---|
| `vendor/jsQR.js` | 256885 | `bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859` |

### qrcode-generator 1.4.4 — pairing QR rendering

- Source: https://github.com/kazuhikoarase/qrcode-generator
  (npm `qrcode-generator@1.4.4`, `qrcode.js` verbatim)
- License: MIT — text in `vendor/qrcode-generator-LICENSE.txt`
  (the upstream package ships no standalone license file; the
  grant is stated in the file header).

| Local file | Bytes | sha256 |
|---|---|---|
| `vendor/qrcode-generator.js` | 56694 | `18ae399f81182bc9de916e9c77b195df20cc58d6f2d55a62b085a299f1bf1780` |
