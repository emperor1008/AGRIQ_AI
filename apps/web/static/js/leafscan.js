/**
 * AGRIQ AI — LeafScan upload helper + demo case.
 * runDemoCase ported verbatim; adds a client-side pre-check mirroring the
 * server rule (JPG/PNG/WebP, <= 5 MiB) so users get early feedback.
 */
(function (global) {
  "use strict";

  var MAX_BYTES = 5 * 1024 * 1024;
  var ALLOWED = ["jpg", "jpeg", "png", "webp"];

  function runDemoCase() {
    var crop = document.getElementById("cropInput");
    var district = document.getElementById("districtSelect");
    var stage = document.getElementById("growthStageSelect");
    var condition = document.getElementById("fieldConditionSelect");
    var form = document.getElementById("farmForm");

    if (crop) crop.value = "Rice";
    if (district) district.value = "Cuttack";
    if (stage) stage.value = "Vegetative";
    if (condition) condition.value = "Humid field";

    setTimeout(function () {
      form.submit();
    }, 250);
  }

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

  global.AgriqLeafScan = { runDemoCase: runDemoCase, bindUploadGuard: bindUploadGuard };
})(window);
