/**
 * AGRIQ AI — Frontend bootstrap.
 * The server renders a small `AgriqBoot` payload (map data, mode, student
 * domain config); this module wires the feature modules to the DOM and
 * exposes the onclick handlers the templates reference.
 */
(function (global) {
  "use strict";

  function boot() {
    var data = global.AgriqBoot || {};
    global.AgriqMap.render();
    global.AgriqDashboard.init();
    global.AgriqAssistant.bindKeyboard();

    // Expose handlers used by inline onclick attributes in templates.
    // Phase 7 (§2/§52): the demo-case handler was removed — it submitted
    // fabricated crop/district/stage/field-condition values into the real form.
    global.refreshLiveWeather = function () { global.AgriqWeather.refresh(); };
    global.quickAskAI = function (t) { global.AgriqAssistant.quickAskAI(t); };
    global.askAGRIQAI = function () { global.AgriqAssistant.ask(); };
    global.fillStudentDemo = function () { global.AgriqDashboard.fillStudentDemo(); };
    global.calcFertilizerDose = function () { global.AgriqDashboard.calcFertilizerDose(); };
    global.calcSeedRate = function () { global.AgriqDashboard.calcSeedRate(); };
    global.convertUnit = function () { global.AgriqDashboard.convertUnit(); };
    global.syncStudentFields = function () { global.AgriqDashboard.syncStudentFields(); };

    if (data.debug) console.info("AGRIQ AI frontend ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window);
