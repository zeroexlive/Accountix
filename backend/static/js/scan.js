/* Accountix invoice scanning (Sprint 31, ADR-060) — in-house,
 * vanilla, self-hosted: no library of ours, no network calls
 * except the app's own JSON endpoints.
 *
 * One module, three modes, chosen by the [data-scan-root]
 * element rendered by templates/_scan_widget.html (desktop
 * invoice forms) or templates/core/scan_phone.html (phone):
 *
 *   sale / purchase — a code (typed, pasted, or sent by a USB HID
 *     scanner gun, which types the code + Enter) is resolved
 *     through the scan lookup endpoint and added to the invoice
 *     formset: same product again -> quantity +1 (POS behavior);
 *     else first empty line; else a new line via the formset's
 *     own add-row button. Camera scanning and the phone-pairing
 *     poll feed the SAME add path.
 *   phone — codes are POSTed to the pairing session's submit
 *     endpoint (the URL token is the credential); the server
 *     resolves them inside the paired company.
 *
 * Every user-visible string arrives server-rendered through
 * data-msg-* attributes on the root element (gettext, both
 * languages) — this file contains no UI language of its own.
 * Decoding: native BarcodeDetector where the browser has it,
 * else the vendored jsQR (QR codes only). Camera needs a secure
 * context (localhost or HTTPS) — the browser enforces that, and
 * the messages below say so plainly when it bites.
 */
(function () {
  "use strict";

  var root = document.querySelector("[data-scan-root]");
  if (!root) return;

  var mode = root.getAttribute("data-scan-mode");
  var lookupUrl = root.getAttribute("data-lookup-url");
  var companyId = root.getAttribute("data-company");
  var createUrl = root.getAttribute("data-session-create-url");
  var submitUrl = root.getAttribute("data-submit-url");

  function msg(key) {
    return root.getAttribute("data-msg-" + key) || "";
  }
  function $(sel) {
    return root.querySelector(sel);
  }
  function csrfToken() {
    var el = document.querySelector("input[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  }

  var input = $("[data-scan-input]");
  var flashEl = $("[data-scan-flash]");
  var flashTimer = null;
  function flash(text, isError) {
    if (!flashEl) return;
    flashEl.textContent = text;
    flashEl.classList.toggle("scan-error", !!isError);
    flashEl.classList.toggle("scan-ok", !isError);
    if (flashTimer) window.clearTimeout(flashTimer);
    flashTimer = window.setTimeout(function () {
      flashEl.textContent = "";
      flashEl.classList.remove("scan-error", "scan-ok");
    }, 4000);
  }

  // ----------------------------------------------------------------
  // Formset integration (desktop modes)
  // ----------------------------------------------------------------

  function setValue(el, value) {
    el.value = value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function bumpQuantity(row) {
    var qty = row.querySelector('input[name$="-quantity"]');
    if (!qty) return;
    var current = parseFloat((qty.value || "0").replace(",", "."));
    if (isNaN(current)) current = 0;
    var next = Math.round((current + 1) * 1000) / 1000;
    setValue(qty, String(next));
    qty.focus();
    qty.select();
  }

  function fillRow(row, product) {
    var select = row.querySelector('select[name$="-product"]');
    if (select) setValue(select, product.id);
    var unit = row.querySelector('select[name$="-unit"]');
    if (unit && product.unit_id) {
      // Only preselect the base unit when the row offers it.
      for (var i = 0; i < unit.options.length; i++) {
        if (unit.options[i].value === product.unit_id) setValue(unit, product.unit_id);
      }
    }
    var qty = row.querySelector('input[name$="-quantity"]');
    if (qty && !qty.value) setValue(qty, "1");
    var price =
      row.querySelector('input[name$="-unit_price"]') ||
      row.querySelector('input[name$="-unit_cost"]');
    var reference = mode === "purchase" ? product.purchase_price : product.sale_price;
    if (price && reference != null && !price.value) setValue(price, reference);
  }

  function addProduct(product) {
    var rows = document.querySelectorAll("#line-rows > tr");
    var emptyRow = null;
    for (var i = 0; i < rows.length; i++) {
      var select = rows[i].querySelector('select[name$="-product"]');
      if (!select) continue;
      if (select.value === product.id) {
        bumpQuantity(rows[i]);
        return;
      }
      if (!select.value && !emptyRow) emptyRow = rows[i];
    }
    if (emptyRow) {
      fillRow(emptyRow, product);
      return;
    }
    var addBtn = document.getElementById("add-line");
    if (addBtn) {
      addBtn.click();
      var grown = document.querySelectorAll("#line-rows > tr");
      if (grown.length) fillRow(grown[grown.length - 1], product);
    }
  }

  // ----------------------------------------------------------------
  // Code intake
  // ----------------------------------------------------------------

  function onProductAdded(product) {
    flash(msg("added").replace("{name}", product.name), false);
  }

  function submitPhoneCode(code) {
    fetch(submitUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code }),
    })
      .then(function (resp) {
        return resp.json().catch(function () {
          return {};
        }).then(function (data) {
          return { ok: resp.ok, status: resp.status, data: data };
        });
      })
      .then(function (r) {
        if (r.ok && r.data.product) {
          onProductAdded(r.data.product);
          var history = $("[data-scan-history]");
          if (history) {
            var li = document.createElement("li");
            li.textContent = r.data.product.name + " (" + r.data.product.sku + ")";
            history.insertBefore(li, history.firstChild);
          }
        } else {
          flash((r.data && r.data.error) || msg("not-found"), true);
        }
      })
      .catch(function () {
        flash(msg("network"), true);
      });
  }

  function lookupAndAdd(code) {
    var url =
      lookupUrl +
      "?code=" +
      encodeURIComponent(code) +
      "&company=" +
      encodeURIComponent(companyId || "");
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        return resp.json().catch(function () {
          return {};
        }).then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (r) {
        if (r.ok && r.data.id) {
          addProduct(r.data);
          onProductAdded(r.data);
        } else {
          flash((r.data && r.data.error) || msg("not-found"), true);
        }
      })
      .catch(function () {
        flash(msg("network"), true);
      });
  }

  function handleCode(raw) {
    var code = (raw || "").trim();
    if (!code) return;
    if (mode === "phone") submitPhoneCode(code);
    else lookupAndAdd(code);
  }

  if (input) {
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        // Scanner guns send Enter; it must never submit the
        // enclosing invoice form.
        ev.preventDefault();
        handleCode(input.value);
        input.value = "";
        input.focus();
      }
    });
    var addBtn = $("[data-scan-add]");
    if (addBtn)
      addBtn.addEventListener("click", function () {
        handleCode(input.value);
        input.value = "";
        input.focus();
      });
  }

  // ----------------------------------------------------------------
  // Camera
  // ----------------------------------------------------------------

  var modal = $("[data-scan-modal]");
  var video = $("[data-scan-video]");
  var modalStatus = $("[data-scan-modal-status]");
  var stream = null;
  var scanTimer = null;
  var detector = null;
  var lastCode = "";
  var lastCodeAt = 0;

  function setModalStatus(text) {
    if (modalStatus) modalStatus.textContent = text || "";
  }

  function onDecode(code) {
    var now = Date.now();
    if (code === lastCode && now - lastCodeAt < 2500) return;
    lastCode = code;
    lastCodeAt = now;
    handleCode(code);
  }

  var scanCanvas = null;
  var scanCtx = null;

  function scanLoop() {
    if (!stream) return;
    if (detector) {
      detector
        .detect(video)
        .then(function (results) {
          if (results && results.length && results[0].rawValue)
            onDecode(results[0].rawValue);
        })
        .catch(function () {})
        .then(function () {
          scanTimer = window.setTimeout(scanLoop, 120);
        });
      return;
    }
    // jsQR fallback: the canvas exists only on this path.
    if (window.jsQR && video.readyState >= 2 && video.videoWidth) {
      if (!scanCanvas) {
        scanCanvas = document.createElement("canvas");
        scanCtx = scanCanvas.getContext("2d", { willReadFrequently: true });
      }
      scanCanvas.width = video.videoWidth;
      scanCanvas.height = video.videoHeight;
      try {
        scanCtx.drawImage(video, 0, 0, scanCanvas.width, scanCanvas.height);
        var img = scanCtx.getImageData(0, 0, scanCanvas.width, scanCanvas.height);
        var found = window.jsQR(img.data, img.width, img.height);
        if (found && found.data) onDecode(found.data);
      } catch (err) {
        /* a frame we cannot read is not an error worth showing */
      }
    }
    scanTimer = window.setTimeout(scanLoop, 150);
  }

  function stopCamera() {
    if (scanTimer) window.clearTimeout(scanTimer);
    scanTimer = null;
    if (stream) {
      stream.getTracks().forEach(function (t) {
        t.stop();
      });
      stream = null;
    }
    if (video) video.srcObject = null;
  }

  function closeModal() {
    stopCamera();
    if (modal) modal.hidden = true;
  }

  var cameraBtn = $("[data-scan-camera]");
  if (cameraBtn && modal && video) {
    cameraBtn.addEventListener("click", function () {
      modal.hidden = false;
      setModalStatus("");
      if (!window.isSecureContext) {
        setModalStatus(msg("insecure"));
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setModalStatus(msg("insecure"));
        return;
      }
      detector = null;
      if ("BarcodeDetector" in window) {
        try {
          detector = new window.BarcodeDetector({
            formats: [
              "qr_code",
              "ean_13",
              "ean_8",
              "upc_a",
              "upc_e",
              "code_128",
              "code_39",
            ],
          });
        } catch (err) {
          detector = null;
        }
      }
      if (!detector) setModalStatus(msg("qr-only"));
      navigator.mediaDevices
        .getUserMedia({ video: { facingMode: "environment" }, audio: false })
        .then(function (s) {
          stream = s;
          video.srcObject = s;
          var played = video.play();
          if (played && played.catch) played.catch(function () {});
          scanLoop();
        })
        .catch(function (err) {
          if (err && err.name === "NotAllowedError") setModalStatus(msg("camera-denied"));
          else setModalStatus(msg("camera-none"));
        });
    });
    var closeBtn = $("[data-scan-modal-close]");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) closeModal();
    });
  }

  // ----------------------------------------------------------------
  // Phone pairing (desktop modes only)
  // ----------------------------------------------------------------

  var connectBtn = $("[data-scan-connect]");
  var panel = $("[data-scan-panel]");
  var pollTimer = null;
  var resultsUrl = null;
  var revokeUrl = null;

  function stopPolling() {
    if (pollTimer) window.clearInterval(pollTimer);
    pollTimer = null;
  }

  function endPairing(statusText) {
    stopPolling();
    stopCamera();
    if (panel) panel.hidden = true;
    if (connectBtn) connectBtn.hidden = false;
    if (statusText) flash(statusText, false);
  }

  function poll() {
    fetch(resultsUrl, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        (data.results || []).forEach(function (r) {
          addProduct(r.product);
          onProductAdded(r.product);
          if (input) input.focus();
        });
        if (!data.live) endPairing(msg("pairing-expired"));
      })
      .catch(function () {
        /* a missed poll is retried by the interval */
      });
  }

  if (connectBtn && panel && createUrl) {
    connectBtn.addEventListener("click", function () {
      connectBtn.disabled = true;
      fetch(createUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrfToken(),
        },
        body: "company=" + encodeURIComponent(companyId || ""),
      })
        .then(function (resp) {
          return resp.json().catch(function () {
            return {};
          }).then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (r) {
          connectBtn.disabled = false;
          if (!r.ok) {
            flash((r.data && r.data.error) || msg("network"), true);
            return;
          }
          resultsUrl = r.data.results_url;
          revokeUrl = r.data.revoke_url;
          var link = $("[data-scan-phone-link]");
          if (link) {
            link.href = r.data.phone_url;
            link.textContent = r.data.phone_url;
          }
          var qrBox = $("[data-scan-qr]");
          if (qrBox && window.qrcode) {
            try {
              var qr = window.qrcode(0, "M");
              qr.addData(r.data.phone_url);
              qr.make();
              qrBox.innerHTML = qr.createSvgTag(4, 8);
            } catch (err) {
              qrBox.textContent = "";
            }
          }
          panel.hidden = false;
          connectBtn.hidden = true;
          stopPolling();
          pollTimer = window.setInterval(poll, 2000);
          poll();
        })
        .catch(function () {
          connectBtn.disabled = false;
          flash(msg("network"), true);
        });
    });
    var disconnectBtn = $("[data-scan-disconnect]");
    if (disconnectBtn)
      disconnectBtn.addEventListener("click", function () {
        if (revokeUrl) {
          fetch(revokeUrl, {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken() },
          }).catch(function () {});
        }
        endPairing("");
      });
    window.addEventListener("beforeunload", stopPolling);
  }
})();
