/**
 * AGRIQ AI — Crop Risk Intelligence panel (Phase 5).
 *
 * Renders the persisted risk run for the active field using the existing
 * AGRIQ design system. Every value shown comes from the backend intelligence
 * pipeline — no numbers are invented here. Status is never colour-only
 * (always paired with a text label), and unavailable/insufficient-data are
 * first-class rendered states.
 */
(function (global) {
  "use strict";

  var STATUS_LABELS = {
    inactive: "No elevated risk",
    monitor: "Monitor",
    elevated: "Elevated",
    high: "High",
    critical: "Critical",
    data_unavailable: "Data unavailable",
    insufficient_data: "Insufficient data",
  };

  var RISK_TITLES = {
    disease_conducive_weather: "Disease-conducive weather",
    heavy_rain_flooding: "Heavy rain / waterlogging",
    heat_stress: "Heat stress",
    water_stress: "Water stress",
    market_volatility: "Market price movement",
  };

  // Assessment method, stated plainly so a rule screening is never mistaken
  // for a validated model output (Phase 5 §7, §22).
  var METHOD_LABELS = {
    rule_based: "Rule-based screening",
    ml: "Model-based assessment",
    hybrid: "Rule + model assessment",
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || status;
  }

  function confidenceWord(value) {
    if (value === null || value === undefined) return "Confidence not available";
    if (value >= 0.75) return "Higher confidence";
    if (value >= 0.5) return "Moderate confidence";
    if (value > 0) return "Low confidence";
    return "Confidence not available";
  }

  function methodLabel(method) {
    return METHOD_LABELS[method] || null;
  }

  function formatTime(iso) {
    if (!iso) return null;
    try {
      return new Date(iso).toLocaleString();
    } catch (err) {
      return iso;
    }
  }

  function card(assessment) {
    var card = el("article", "crop-risk-card crop-risk-card--" + assessment.status);
    card.setAttribute("aria-label", RISK_TITLES[assessment.risk_type] + " risk: " + statusLabel(assessment.status));

    var head = el("div", "crop-risk-card__head");
    var title = el("h3", "crop-risk-card__title", RISK_TITLES[assessment.risk_type] || assessment.risk_type);
    var badge = el("span", "crop-risk-badge crop-risk-badge--" + assessment.status, statusLabel(assessment.status));
    badge.setAttribute("role", "status");
    head.appendChild(title);
    head.appendChild(badge);
    card.appendChild(head);

    if (assessment.threat) {
      card.appendChild(el("p", "crop-risk-card__threat", assessment.threat));
    }

    // Honest unavailable / insufficient states — never a fake complete card.
    if (assessment.status === "data_unavailable" || assessment.status === "insufficient_data") {
      var note = el("p", "crop-risk-card__note",
        assessment.status === "data_unavailable"
          ? "There is not enough verified data available to assess this risk right now."
          : "There is not enough verified data to assess this risk.");
      card.appendChild(note);
      var unavailableMethod = methodLabel(assessment.assessment_method);
      if (unavailableMethod) {
        card.appendChild(el("p", "crop-risk-card__method", unavailableMethod));
      }
      return card;
    }

    if (assessment.probability !== null && assessment.probability !== undefined) {
      var prob = el("p", "crop-risk-card__prob");
      prob.appendChild(el("span", "crop-risk-card__prob-label", "Likelihood: "));
      // One decimal at most — never excessive precision.
      prob.appendChild(document.createTextNode(Math.round(assessment.probability * 100) + "%"));
      card.appendChild(prob);
      // The backend states what the number is. Render it verbatim so the screen
      // can never imply a calibrated probability the backend did not claim.
      if (assessment.probability_interpretation) {
        var interpretation = el("p", "crop-risk-card__note",
          assessment.probability_interpretation.charAt(0).toUpperCase() +
          assessment.probability_interpretation.slice(1) + ".");
        card.appendChild(interpretation);
      }
    }

    if (assessment.reasons && assessment.reasons.length) {
      var why = el("details", "crop-risk-card__why");
      why.appendChild(el("summary", null, "Why this assessment?"));
      var list = el("ul", "crop-risk-card__reasons");
      assessment.reasons.forEach(function (reason) {
        list.appendChild(el("li", null, reason));
      });
      why.appendChild(list);
      card.appendChild(why);
    }

    if (assessment.actions && assessment.actions.length) {
      var actions = el("div", "crop-risk-card__actions");
      actions.appendChild(el("strong", null, "Recommended:"));
      actions.appendChild(el("p", null, assessment.actions[0]));
      card.appendChild(actions);
      if (assessment.actions.length > 1) {
        var more = el("details", "crop-risk-card__more-actions");
        more.appendChild(el("summary", null, "More steps"));
        var moreList = el("ul");
        assessment.actions.slice(1).forEach(function (action) {
          moreList.appendChild(el("li", null, action));
        });
        more.appendChild(moreList);
        card.appendChild(more);
      }
    }

    if (assessment.evidence && assessment.evidence.length) {
      var evidence = el("details", "crop-risk-card__evidence");
      evidence.appendChild(el("summary", null, "Evidence & freshness"));
      var evList = el("ul");
      assessment.evidence.forEach(function (item) {
        var li = el("li");
        li.appendChild(el("span", "crop-risk-evidence__source", item.source || "Unknown source"));
        if (item.detail) li.appendChild(document.createTextNode(" — " + item.detail));
        var freshness = item.freshness && item.freshness !== "unavailable"
          ? " (" + item.freshness + ")"
          : "";
        if (item.observed_at) {
          li.appendChild(el("span", "crop-risk-evidence__time",
            " · observed " + formatTime(item.observed_at) + freshness));
        } else if (item.retrieved_at) {
          li.appendChild(el("span", "crop-risk-evidence__time",
            " · retrieved " + formatTime(item.retrieved_at) + freshness));
        }
        evList.appendChild(li);
      });
      evidence.appendChild(evList);
      card.appendChild(evidence);
    }

    var foot = el("div", "crop-risk-card__foot");
    foot.appendChild(el("span", "crop-risk-card__confidence",
      confidenceWord(assessment.confidence) +
      (assessment.confidence ? " (" + Math.round(assessment.confidence * 100) + "%)" : "")));
    var method = methodLabel(assessment.assessment_method);
    if (method) {
      var methodNote = el("span", "crop-risk-card__method", method);
      if (assessment.calibration_status && assessment.calibration_status !== "validated") {
        methodNote.setAttribute("title", "Calibration not validated for this assessment.");
      }
      foot.appendChild(methodNote);
    }
    if (assessment.requires_expert_confirmation) {
      foot.appendChild(el("span", "crop-risk-card__expert",
        "Expert confirmation recommended — contact your KVK or agriculture officer."));
    }
    card.appendChild(foot);

    // Action tracking (§27): planned / completed / skipped / needs help.
    if (assessment.actions && assessment.actions.length) {
      card.appendChild(actionBar(assessment.id));
    }
    return card;
  }

  function actionBar(riskId) {
    var bar = el("div", "crop-risk-action-bar");
    bar.setAttribute("aria-label", "Record what you did");
    var planned = el("button", "crop-risk-action-btn", "Will do");
    var done = el("button", "crop-risk-action-btn", "Did it");
    var skip = el("button", "crop-risk-action-btn", "Not now");
    var help = el("button", "crop-risk-action-btn", "Need help");
    [planned, done, skip, help].forEach(function (btn) {
      btn.type = "button";
      btn.addEventListener("click", function () {
        record(riskId, btn.getAttribute("data-status"), bar);
      });
    });
    planned.setAttribute("data-status", "planned");
    done.setAttribute("data-status", "completed");
    skip.setAttribute("data-status", "skipped");
    help.setAttribute("data-status", "needs_help");
    bar.appendChild(planned);
    bar.appendChild(done);
    bar.appendChild(skip);
    bar.appendChild(help);
    return bar;
  }

  function record(riskId, status, bar) {
    global.AgriqAPI.riskAction(riskId, { action_status: status }).then(function () {
      var note = el("span", "crop-risk-action-note", "Recorded. Thank you.");
      note.setAttribute("role", "status");
      bar.replaceWith(note);
    }).catch(function () {
      var note = el("span", "crop-risk-action-note crop-risk-action-note--error",
        "Could not save right now. You can try again.");
      note.setAttribute("role", "alert");
      bar.replaceWith(note);
    });
  }

  function render(payload) {
    var container = document.getElementById("cropRiskPanelBody");
    if (!container) return;
    container.textContent = "";

    if (!payload || payload.ok === false) {
      container.appendChild(el("p", "crop-risk-empty",
        (payload && payload.message) || "Risk analysis is not available right now."));
      return;
    }

    var meta = el("p", "crop-risk-meta");
    var freshnessText = payload.weather && payload.weather.available
      ? "Weather: " + payload.weather.freshness
      : "Weather unavailable";
    meta.appendChild(el("span", "crop-risk-meta__item", freshnessText));
    if (payload.weather && payload.weather.retrieved_at) {
      meta.appendChild(el("span", "crop-risk-meta__item",
        "Last updated " + formatTime(payload.weather.retrieved_at)));
    }
    container.appendChild(meta);

    var active = 0;
    payload.assessments.forEach(function (assessment) {
      if (["monitor", "elevated", "high", "critical"].indexOf(assessment.status) !== -1) active += 1;
      container.appendChild(card(assessment));
    });

    if (active === 0) {
      var allClear = el("p", "crop-risk-allclear",
        "No elevated risk detected from the latest verified data.");
      allClear.setAttribute("role", "status");
      container.insertBefore(allClear, container.firstChild.nextSibling);
    }
  }

  function setLoading() {
    var container = document.getElementById("cropRiskPanelBody");
    if (container) container.textContent = "Analyzing current field conditions…";
  }

  function setError(message) {
    var container = document.getElementById("cropRiskPanelBody");
    if (!container) return;
    container.textContent = "";
    container.appendChild(el("p", "crop-risk-error", message || "Risk data is temporarily unavailable."));
  }

  function refresh(force) {
    var fieldId = global.AgriqPanelState && global.AgriqPanelState.activeFieldId;
    if (!fieldId) return Promise.resolve();
    setLoading();
    return global.AgriqAPI.analyzeFieldRisk(fieldId, { force: !!force })
      .then(render)
      .catch(function () { setError(); });
  }

  function init() {
    var button = document.getElementById("cropRiskRefresh");
    if (button) {
      button.addEventListener("click", function () { refresh(true); });
    }
    // Discover the active field from the shared farmer context, then load
    // the stored run (first visit shows the quiet empty state on failure).
    if (!global.AgriqAPI || !global.AgriqAPI.farmerContext) return;
    global.AgriqAPI.farmerContext().then(function (payload) {
      // The endpoint answers {ok, context} — read the nested context.
      var field = payload && payload.context && payload.context.field;
      if (!field || !field.id) return;
      global.AgriqPanelState = global.AgriqPanelState || {};
      global.AgriqPanelState.activeFieldId = field.id;
      var label = document.getElementById("cropRiskPanelField");
      if (label && field.name) {
        label.textContent = field.name + (field.area ? " · " + field.area + " " + (field.area_unit || "") : "");
      }
      return global.AgriqAPI.currentFieldRisk(field.id).then(render).catch(function () {
        // No stored run yet — offer the refresh button as the entry point.
        var container = document.getElementById("cropRiskPanelBody");
        if (container) {
          container.textContent = "";
          container.appendChild(el("p", "crop-risk-empty",
            "Run an analysis to see current risk conditions for this field."));
        }
      });
    }).catch(function () { /* not onboarded — panel stays empty */ });
  }

  global.RiskPanel = { init: init, refresh: refresh, render: render };

  if (document.readyState !== "loading") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})(window);
