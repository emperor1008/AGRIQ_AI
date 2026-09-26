/**
 * AGRIQ AI — LeafScan upload helper.
 * Client-side pre-check mirroring the server rule (JPG/PNG/WebP, <= 5 MiB)
 * so users get early feedback before the upload round-trip.
 *
 * Phase 7 (§2/§4/§52): the former demo-case helper was REMOVED. It filled the
 * form with context the farmer never entered (a fixed crop, district, growth
 * stage and field condition) and auto-submitted it to the real analysis form,
 * so fabricated observations were processed and persisted as farmer-reported
 * data. Production code must never fabricate farmer context; a labelled test
 * fixture can only live inside the automated test suite.
 */
(function (global) {
  "use strict";

  var MAX_BYTES = 5 * 1024 * 1024;
  var ALLOWED = ["jpg", "jpeg", "png", "webp"];

  function bindUploadGuard() {
    var input = document.querySelector('.leaf-upload input[type="file"]');
    if (!input) return;
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      var ext = (file.name.split(".").pop() || "").toLowerCase();
      if (ALLOWED.indexOf(ext) === -1 || file.size > MAX_BYTES) {
        alert("Use a clear JPG, PNG or WebP under 5 MiB.");
        input.value = "";
      }
    });
  }

  global.AgriqLeafScan = { bindUploadGuard: bindUploadGuard };
})(window);
