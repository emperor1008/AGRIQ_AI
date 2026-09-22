/**
 * AGRIQ AI — Live weather console.
 * renderWeatherConsole/refreshLiveWeather ported verbatim from the inline
 * template script; only the transport now goes through AgriqAPI.
 */
(function (global) {
  "use strict";

  function renderWeatherConsole(consoleData) {
    var nowGrid = document.getElementById("weatherNowGrid");
    var daily = document.getElementById("dailyWeatherRows");
    if (!consoleData || !nowGrid) return;

    // Unavailable state: show the canonical message, never generated values.
    if (consoleData.available === false) {
      nowGrid.innerHTML =
        '<div class="weather-tile live-tile"><span>Status</span><strong>' +
        (consoleData.live_badge || "UNAVAILABLE") + '</strong><small>' +
        (consoleData.message || "Verified data is currently unavailable.") + '</small></div>';
      var meta0 = document.querySelector(".weather-meta-card");
      if (meta0) {
        meta0.innerHTML = "<b>Source:</b> " + (consoleData.source_note || "");
      }
      if (daily) daily.innerHTML = "";
      return;
    }

    var current = consoleData.current || {};
    nowGrid.innerHTML =
      '<div class="weather-tile"><span>Temperature</span><strong>' + (current.temp ?? "–") + '°C</strong><small>' +
      (current.condition || "Changing weather") + '</small></div>' +
      '<div class="weather-tile"><span>Humidity</span><strong>' + (current.humidity ?? "–") + '%</strong><small>Leaf wetness indicator</small></div>' +
      '<div class="weather-tile"><span>Rain Now</span><strong>' + (current.rain ?? "–") + ' mm</strong><small>Current precipitation</small></div>' +
      '<div class="weather-tile"><span>Wind</span><strong>' + (current.wind ?? "–") + ' km/h</strong><small>Spray timing factor</small></div>' +
      '<div class="weather-tile live-tile"><span>Status</span><strong>' + consoleData.live_badge + '</strong><small>Updated ' + consoleData.updated_at + '</small></div>';

    var meta = document.querySelector(".weather-meta-card");
    if (meta) {
      meta.innerHTML =
        "<b>Weather time:</b> " + (current.time || "") +
        "<br><b>Source:</b> " + (consoleData.source_note || "") +
        "<br><b>Soil & water note:</b> " + (consoleData.soil_water_note || "");
    }

    document.getElementById("fieldAlertText").textContent = consoleData.field_alert || "";
    document.getElementById("diseaseWindowText").textContent = consoleData.disease_window || "";
    document.getElementById("irrigationNoteText").textContent = consoleData.irrigation_note || "";
    document.getElementById("sprayWindowText").textContent = consoleData.spray_window || "";

    if (daily) {
      daily.innerHTML = (consoleData.daily || [])
        .map(function (d) {
          return (
            '<div class="daily-card"><b>' + d.day + "</b><span>" + d.temp_min + "°C - " + d.temp_max +
            '°C</span><small>' + d.rain + " mm rain • " + d.pop + '% chance</small><small>' + d.condition + "</small></div>"
          );
        })
        .join("");
    }
  }

  async function refreshLiveWeather() {
    var district = (document.getElementById("districtSelect") || {}).value || "Cuttack";
    var crop = (document.getElementById("cropInput") || {}).value || "Rice";
    var stage = (document.getElementById("growthStageSelect") || {}).value || "Vegetative";
    var condition = (document.getElementById("fieldConditionSelect") || {}).value || "Normal field";
    try {
      var data = await global.AgriqAPI.fetchLiveWeather({
        district: district,
        crop: crop,
        growth_stage: stage,
        field_condition: condition,
      });
      renderWeatherConsole(data.weather_console);
    } catch (error) {
      alert("Weather refresh is temporarily unavailable. Existing forecast remains visible.");
    }
  }

  global.AgriqWeather = { render: renderWeatherConsole, refresh: refreshLiveWeather };
})(window);
