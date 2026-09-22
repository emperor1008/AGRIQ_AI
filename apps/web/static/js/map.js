/**
 * AGRIQ AI — Odisha GeoRisk map (Leaflet).
 * Rendered behaviour is identical to the previous inline script; data is
 * injected by the server into window.AgriqBoot.mapData.
 */
(function (global) {
  "use strict";

  var MARKER_COLORS = { red: "#ef4444", orange: "#f97316", yellow: "#facc15", green: "#22c55e" };

  function markerColor(colorName) {
    return MARKER_COLORS[colorName] || "#22c55e";
  }

  function renderMap() {
    var el = document.getElementById("map");
    if (!el || typeof L === "undefined") return;

    var boot = global.AgriqBoot || {};
    var mapData = boot.mapData || [];

    var map = L.map("map", { zoomControl: true, scrollWheelZoom: true }).setView([20.45, 85.65], 7);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 11,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);

    mapData.forEach(function (item) {
      var selected = item.selected;
      var analyzed = item.analysed === true && item.risk !== null;
      var color = markerColor(item.color);
      // Unanalysed districts get a neutral small marker; no fake risk sizing.
      var radius = selected ? 19000 : (analyzed ? 11500 + item.risk * 60 : 9000);

      var marker = L.circle([item.lat, item.lon], {
        radius: radius,
        color: color,
        fillColor: color,
        fillOpacity: selected ? 0.42 : (analyzed ? 0.24 : 0.10),
        weight: selected ? 5 : 2,
        dashArray: analyzed ? null : "4 6",
        className: selected ? "selected-district-circle" : "",
      }).addTo(map);

      marker.bindPopup(
        '<div class="map-popup">' +
          "<b>" + item.district + "</b><br>" +
          (analyzed
            ? "Risk: <b>" + item.risk + "% • " + item.status + "</b><br>"
            : item.awaiting || "Awaiting verified analysis." + "<br>") +
          (item.temp !== null
            ? "Weather: " + item.temp + "°C • " + item.humidity + "% humidity • " + item.rain + " mm rain"
            : (analyzed ? "Selected analysis district" : "Run an analysis to see verified results")) +
          "</div>"
      );

      if (selected) {
        map.setView([item.lat, item.lon], 8);
        marker.openPopup();
      }
    });
  }

  global.AgriqMap = { render: renderMap, markerColor: markerColor };
})(window);
