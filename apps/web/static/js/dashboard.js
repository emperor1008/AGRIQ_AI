/**
 * AGRIQ AI — Dashboard behaviour.
 * Student form syncing, demo fill, calculators and smooth anchor navigation
 * ported verbatim from the inline template script.
 */
(function (global) {
  "use strict";

  function setSelectOptions(select, values) {
    if (!select) return;
    select.innerHTML = "";
    (values || []).forEach(function (value) {
      var option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
  }

  function syncStudentFields() {
    var areaSelect = document.getElementById("studentAreaSelect");
    if (!areaSelect) return;
    var boot = global.AgriqBoot || {};
    var config = (boot.studentDomainConfig || {})[areaSelect.value] || {};
    setSelectOptions(document.getElementById("studentTopicSelect"), config.topics || []);
    setSelectOptions(document.getElementById("studentPestSelect"), config.pests || []);
    setSelectOptions(document.getElementById("studentDiseaseSelect"), config.diseases || []);

    var show = new Set(
      ["level", "purpose", "domain", "topic", "output_format", "study_depth", "prompt"].concat(config.show || [])
    );
    document.querySelectorAll("#studentStudyForm [data-field]").forEach(function (box) {
      var field = box.getAttribute("data-field");
      box.style.display = show.has(field) ? "" : "none";
    });
  }

  function fillStudentDemo() {
    var area = document.getElementById("studentAreaSelect");
    if (area) area.value = "Plant Pathology";
    syncStudentFields();
    var topic = document.getElementById("studentTopicSelect");
    var crop = document.getElementById("studentCropInput");
    var disease = document.getElementById("studentDiseaseSelect");
    var pest = document.getElementById("studentPestSelect");
    var prompt = document.getElementById("studentPromptBox");
    if (topic) topic.value = "Plant Disease Triangle";
    if (crop) crop.value = "Rice";
    if (disease) disease.value = "Blast";
    if (pest) pest.value = "Brown Plant Hopper";
    if (prompt) prompt.value = "Explain rice blast in easy way with disease triangle, lifecycle, exam answer, viva and research plan.";
  }

  function calcFertilizerDose() {
    var nutrient = parseFloat((document.getElementById("nutrientKg") || {}).value || 0);
    var pct = parseFloat((document.getElementById("nutrientPct") || {}).value || 0);
    var out = document.getElementById("fertilizerResult");
    if (!out) return;
    if (nutrient <= 0 || pct <= 0) { out.textContent = "Enter valid values."; return; }
    out.textContent = (nutrient / (pct / 100)).toFixed(2) + " kg fertilizer required";
  }

  function calcSeedRate() {
    var base = parseFloat((document.getElementById("baseSeedRate") || {}).value || 0);
    var germ = parseFloat((document.getElementById("germinationPct") || {}).value || 0);
    var out = document.getElementById("seedRateResult");
    if (!out) return;
    if (base <= 0 || germ <= 0) { out.textContent = "Enter valid values."; return; }
    out.textContent = ((base * 100) / germ).toFixed(2) + " kg/ha adjusted seed rate";
  }

  function convertUnit() {
    var value = parseFloat((document.getElementById("unitValue") || {}).value || 0);
    var type = (document.getElementById("unitType") || {}).value || "ha_acre";
    var out = document.getElementById("unitResult");
    if (!out) return;
    var map = {
      ha_acre: [value * 2.471, "acre"],
      acre_ha: [value * 0.4047, "hectare"],
      q_kg: [value * 100, "kg"],
      mm_litre_ha: [value * 10000, "litres over 1 ha"],
    };
    var result = map[type] || [value, ""];
    out.textContent = result[0].toFixed(2) + " " + result[1];
  }

  function bindSmoothAnchors() {
    document
      .querySelectorAll('.side-rail a[href^="#"], .section-launcher a[href^="#"]')
      .forEach(function (link) {
        link.addEventListener("click", function (e) {
          var target = document.querySelector(this.getAttribute("href"));
          if (!target) return;
          e.preventDefault();
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          target.classList.add("section-flash");
          setTimeout(function () {
            target.classList.remove("section-flash");
          }, 900);
        });
      });
  }

  function init() {
    syncStudentFields();
    var areaSelect = document.getElementById("studentAreaSelect");
    if (areaSelect) areaSelect.addEventListener("change", syncStudentFields);
    bindSmoothAnchors();
    if (global.AgriqLeafScan) global.AgriqLeafScan.bindUploadGuard();
  }

  global.AgriqDashboard = {
    init: init,
    syncStudentFields: syncStudentFields,
    fillStudentDemo: fillStudentDemo,
    calcFertilizerDose: calcFertilizerDose,
    calcSeedRate: calcSeedRate,
    convertUnit: convertUnit,
  };
})(window);
