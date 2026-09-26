/**
 * AGRIQ AI — Farm-to-Market panel (Phase 6).
 *
 * Renders the structured market-intelligence payloads using the existing AGRIQ
 * design system. Every number shown comes from an official AGMARKNET record or
 * from a forecast the backend actually produced — nothing is computed here.
 * Unavailable, insufficient-data and "net value incomplete" are first-class
 * states, and a gross value is never relabelled as profit.
 */
(function (global) {
  "use strict";

  var FRESHNESS_LABELS = {
    fresh: "Fresh",
    aging: "Aging",
    stale: "Stale",
    expired: "Expired",
    unavailable: "Freshness unavailable",
  };

  var DECISION_LABELS = {
    SELL_NOW: "Sell now",
    WAIT: "Wait",
    MONITOR: "Monitor",
    INSUFFICIENT_DATA: "Not enough evidence",
  };

  /** Which way each evidence kind points, in the agent's own words. */
  var EVIDENCE_EFFECTS = {
    sell: "favours selling",
    hold: "favours waiting",
    monitor: "watch the market",
  };

  var DEMAND_REASONS = {
    arrivals_not_published_by_configured_source:
      "The configured official source publishes prices, not arrival quantities, so no demand figure is produced.",
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function rupee(value) {
    return value === null || value === undefined ? "—" : value + " ₹/quintal";
  }

  function formatTime(iso) {
    if (!iso) return null;
    var parsed = new Date(iso);
    return isNaN(parsed.getTime()) ? iso : parsed.toLocaleString();
  }

  function setBody(node) {
    var container = document.getElementById("marketPanelBody");
    if (!container) return null;
    container.textContent = "";
    if (node) container.appendChild(node);
    container.setAttribute("aria-busy", "false");
    return container;
  }

  function message(text, className) {
    setBody(el("p", className || "market-empty", text));
  }

  function metaRow(items) {
    var meta = el("div", "market-meta");
    items.forEach(function (item) {
      if (!item || !item.text) return;
      var span = el("span", "market-meta__item" + (item.warn ? " market-meta__item--warn" : ""), item.text);
      meta.appendChild(span);
    });
    return meta;
  }

  /** Provenance / freshness line — the honest "how old is this" statement. */
  function provenanceNotes(payload) {
    var provenance = (payload && payload.provenance) || {};
    var status = provenance.freshness_status || "unavailable";
    var items = [{
      text: "Data: " + (FRESHNESS_LABELS[status] || status),
      warn: status === "stale" || status === "expired" || status === "unavailable",
    }];
    if (provenance.age_minutes !== null && provenance.age_minutes !== undefined) {
      items.push({ text: "Age: " + provenance.age_minutes + " min" });
    }
    if (provenance.price_date) items.push({ text: "Price date: " + provenance.price_date });
    if (provenance.source) items.push({ text: provenance.source });
    if (payload && payload.provider && payload.provider.requested && payload.provider.available === false) {
      items.push({
        text: "Provider unavailable: " + (payload.provider.reason || "unknown reason"),
        warn: true,
      });
    }
    return items;
  }

  function priceCard(payload) {
    var card = el("article", "market-card");
    var head = el("div", "market-card__head");
    head.appendChild(el("h3", "market-card__title",
      "Official prices · " + (payload.crop_name || payload.crop || "your crop")));
    var trend = payload.trend || {};
    var badge = el("span", "market-badge market-badge--" + (trend.status === "ok" ? trend.direction : "stable"),
      trend.status === "ok"
        ? trend.direction + " " + trend.change_percent + "%"
        : "trend unavailable");
    head.appendChild(badge);
    card.appendChild(head);

    var prices = payload.latest_prices || [];
    if (!prices.length) {
      var reason = (payload.provider && payload.provider.reason) || "no_official_records";
      card.appendChild(el("p", "market-card__note",
        "No official record is available for this crop in your district right now (" + reason + "). " +
        "AGRIQ shows no estimated price."));
      return card;
    }
    var rows = el("div", "market-rows");
    prices.slice(0, 4).forEach(function (row) {
      var line = el("div", "market-row");
      var left = el("div");
      left.appendChild(el("div", "market-row__market", row.market || "Unnamed market"));
      left.appendChild(el("span", "market-row__note",
        (row.variety ? row.variety + " · " : "") + (row.price_date || "date unavailable")));
      line.appendChild(left);
      line.appendChild(el("span", "market-row__price", rupee(row.modal_price)));
      rows.appendChild(line);
    });
    card.appendChild(rows);

    if (trend.status !== "ok" && trend.reason) {
      card.appendChild(el("p", "market-card__note", "Trend: " + trend.reason + "."));
    }
    var demand = payload.demand || {};
    if (demand.available === false) {
      card.appendChild(el("p", "market-card__note",
        DEMAND_REASONS[demand.reason] || demand.note || "Demand data is not available from the configured source."));
    }
    (payload.limitations || []).slice(0, 2).forEach(function (note) {
      card.appendChild(el("p", "market-card__note", note));
    });
    return card;
  }

  function comparisonCard(payload) {
    var comparison = payload.comparison || {};
    var groups = comparison.groups || [];
    if (!groups.length) return null;
    var card = el("article", "market-card");
    card.appendChild(el("h3", "market-card__title", "Market comparison"));
    card.appendChild(el("p", "market-card__note", comparison.gross_vs_net || ""));

    groups.slice(0, 2).forEach(function (group) {
      var rows = el("div", "market-rows");
      (group.markets || []).slice(0, 4).forEach(function (row) {
        var line = el("div", "market-row");
        var left = el("div");
        left.appendChild(el("div", "market-row__market", row.market || "Unnamed market"));
        var detail = [];
        if (row.distance_km !== null && row.distance_km !== undefined) {
          detail.push(row.distance_km + " km straight line");
        } else if (row.distance_unavailable_reason) {
          detail.push("distance unavailable");
        }
        if (row.estimated_transport_cost !== null && row.estimated_transport_cost !== undefined) {
          detail.push("transport ~" + row.estimated_transport_cost + " ₹");
        }
        left.appendChild(el("span", "market-row__note", detail.join(" · ")));
        line.appendChild(left);

        var right = el("div");
        right.appendChild(el("span", "market-row__price", rupee(row.modal_price)));
        var economics = row.economics || {};
        if (economics.label === "estimated_net_value") {
          right.appendChild(el("div", "market-row__net",
            "Estimated net " + economics.estimated_net_value + " ₹"));
        } else if (economics.status === "incomplete") {
          right.appendChild(el("div", "market-row__net",
            "Net value incomplete — missing: " + (economics.missing_costs || []).join(", ")));
        }
        line.appendChild(right);
        rows.appendChild(line);
      });
      card.appendChild(rows);
    });
    (comparison.logistics_limitations || []).slice(0, 1).forEach(function (note) {
      card.appendChild(el("p", "market-card__note", note));
    });
    return card;
  }

  function timingCard(payload) {
    var card = el("article", "market-card");
    var head = el("div", "market-card__head");
    head.appendChild(el("h3", "market-card__title", "Sell or wait"));
    var decision = payload.decision || "INSUFFICIENT_DATA";
    var badge = el("span", "market-badge" + (decision === "INSUFFICIENT_DATA" ? " market-badge--incomplete" : ""),
      DECISION_LABELS[decision] || decision);
    head.appendChild(badge);
    card.appendChild(head);

    card.appendChild(el("p", "market-card__decision",
      decision === "INSUFFICIENT_DATA"
        ? "AGRIQ cannot advise timing from the verified evidence available."
        : "Evidence points to: " + (DECISION_LABELS[decision] || decision) + "."));

    // A fact that moved the decision must never be hidden behind a truncated list
    // of neutral observations, so directional evidence is listed first and each
    // line states which way it points.
    var evidence = payload.evidence || [];
    var directional = evidence.filter(function (item) { return item.direction !== "neutral"; });
    var neutral = evidence.filter(function (item) { return item.direction === "neutral"; });
    var shown = directional.concat(neutral).slice(0, 6);
    if (shown.length) {
      var list = el("ul", "market-card__detail");
      shown.forEach(function (item) {
        var suffix = EVIDENCE_EFFECTS[item.direction];
        list.appendChild(el("li", null, item.observation + (suffix ? " — " + suffix : "")));
      });
      card.appendChild(list);
    }
    if (evidence.length > shown.length) {
      card.appendChild(el("p", "market-card__note",
        (evidence.length - shown.length) + " further observed fact(s) are recorded in the evidence report."));
    }
    if (payload.reason) card.appendChild(el("p", "market-card__note", payload.reason));
    var missing = payload.missing_information || [];
    if (missing.length) {
      card.appendChild(el("p", "market-card__note", "Missing information: " + missing.join("; ") + "."));
    }
    var risks = payload.risks || [];
    risks.forEach(function (risk) {
      card.appendChild(el("p", "market-card__note",
        "Crop risk in context: " + (risk.threat || risk.risk_type) + " (" + risk.status + ")."));
    });
    var confidence = payload.confidence || {};
    var foot = el("div", "market-card__foot");
    foot.appendChild(el("span", null,
      confidence.status === "not_calibrated"
        ? "Confidence not calibrated — no probability is claimed."
        : "Confidence: " + (confidence.status || "unavailable")));
    card.appendChild(foot);
    if (payload.requires_expert_confirmation) {
      card.appendChild(el("p", "market-card__expert",
        "Confirm with your local agriculture officer or KVK before acting on this timing view."));
    }
    return card;
  }

  function cropOptionsCard(payload) {
    var card = el("article", "market-card");
    card.appendChild(el("h3", "market-card__title", "Crop options for your district"));
    if (!payload || payload.ok === false) {
      card.appendChild(el("p", "market-card__note",
        (payload && payload.message) || "Crop options are not available right now."));
      return card;
    }
    var options = (payload.options || []).slice(0, 5);
    if (!options.length) {
      card.appendChild(el("p", "market-card__note", "No candidate crop could be evaluated."));
      return card;
    }
    var rows = el("div", "market-rows");
    options.forEach(function (option) {
      var line = el("div", "market-row");
      var left = el("div");
      left.appendChild(el("div", "market-row__market", option.crop_name || option.crop));
      var first = (option.reasons || [])[0];
      left.appendChild(el("span", "market-row__note", first || "See evidence for details."));
      line.appendChild(left);
      var right = el("div");
      var market = option.market || {};
      right.appendChild(el("span", "market-row__price",
        market.price_context_available
          ? market.latest_modal_price + " ₹/quintal"
          : "no stored price"));
      right.appendChild(el("div", "market-row__net", option.recommendation_status));
      line.appendChild(right);
      rows.appendChild(line);
    });
    card.appendChild(rows);
    card.appendChild(el("p", "market-card__note", payload.ranking_method || ""));
    if (payload.market_price_context) {
      card.appendChild(el("p", "market-card__note", payload.market_price_context));
    }
    return card;
  }

  /**
   * Cost-completeness view. Gross value is price × quantity; a net value appears
   * only when every cost component came from the farmer, and a missing component
   * is named here rather than estimated.
   */
  function economicsCard(payload) {
    var comparison = payload.comparison || {};
    var groups = comparison.groups || [];
    if (!groups.length) return null;
    var card = el("article", "market-card");
    card.appendChild(el("h3", "market-card__title", "Value and cost check"));

    var rows = el("div", "market-rows");
    var quantityKnown = false;
    (groups[0].markets || []).slice(0, 4).forEach(function (row) {
      var economics = row.economics || {};
      if (economics.quantity_quintals) quantityKnown = true;

      var line = el("div", "market-row");
      var left = el("div");
      left.appendChild(el("div", "market-row__market", row.market || "Unnamed market"));
      var detail = [];
      if (row.distance_km !== null && row.distance_km !== undefined) {
        detail.push(row.distance_km + " km straight-line proxy");
      } else {
        detail.push("distance unavailable");
      }
      if (row.estimated_transport_cost !== null && row.estimated_transport_cost !== undefined) {
        detail.push("transport from your figures: " + row.estimated_transport_cost + " ₹");
      }
      left.appendChild(el("span", "market-row__note", detail.join(" · ")));
      line.appendChild(left);

      var right = el("div");
      if (economics.status === "insufficient_data") {
        right.appendChild(el("div", "market-row__net",
          economics.reason || "no value can be computed from the records held"));
      } else {
        right.appendChild(el("div", "market-row__price", "Gross " + economics.gross_value + " ₹"));
        right.appendChild(el("div", "market-row__net",
          economics.label === "estimated_net_value"
            ? "Estimated net " + economics.estimated_net_value + " ₹ — all costs from your figures"
            : "Net value incomplete — missing: " + (economics.missing_costs || []).join(", ")));
      }
      line.appendChild(right);
      rows.appendChild(line);
    });
    card.appendChild(rows);

    if (!quantityKnown) {
      card.appendChild(el("p", "market-card__note",
        "Enter the quantity you plan to sell to see a gross value. AGRIQ does not estimate yield, "
        + "so it cannot fill this in."));
    }
    card.appendChild(el("p", "market-card__note",
      "Gross value is price × quantity — not profit. Every cost comes only from the figures you "
      + "entered; AGRIQ has no verified freight, input-cost or yield source."));
    if (groups[0].comparison_note) {
      card.appendChild(el("p", "market-card__note", groups[0].comparison_note));
    }
    (comparison.logistics_limitations || []).slice(0, 2).forEach(function (note) {
      card.appendChild(el("p", "market-card__note", note));
    });
    return card;
  }

  function renderLogistics(payload) {
    if (!payload || payload.ok === false) {
      message((payload && payload.message) || "Market comparison is unavailable right now.", "market-error");
      return;
    }
    var groups = ((payload.comparison || {}).groups) || [];
    if (!groups.length) {
      setBody(el("p", "market-empty",
        "No official market record is available for this crop and district, so no cost comparison "
        + "can be computed and no price is estimated."));
      return;
    }
    var container = setBody(null);
    if (!container) return;
    container.appendChild(metaRow(provenanceNotes(payload)));
    container.appendChild(economicsCard(payload));
  }

  function renderOverview(payload) {
    if (!payload || payload.ok === false) {
      message((payload && payload.message) || "Market intelligence is not available right now.", "market-error");
      return;
    }
    if (!payload.latest_prices || !payload.latest_prices.length) {
      setBody(el("p", "market-empty",
        "No official market record is available for this crop and district yet."));
      return;
    }
    var container = setBody(null);
    if (!container) return;
    container.appendChild(metaRow(provenanceNotes(payload)));
    container.appendChild(priceCard(payload));
    var comparison = comparisonCard(payload);
    if (comparison) container.appendChild(comparison);
  }

  function renderTiming(payload) {
    if (!payload || payload.ok === false) {
      message((payload && payload.message) || "Timing advice is unavailable right now.", "market-error");
      return;
    }
    var container = setBody(null);
    if (!container) return;
    container.appendChild(metaRow(provenanceNotes(payload)));
    container.appendChild(timingCard(payload));
  }

  function renderCropOptions(payload) {
    if (!payload || payload.ok === false) {
      message((payload && payload.message) || "Crop options are unavailable right now.", "market-error");
      return;
    }
    var container = setBody(null);
    if (!container) return;
    // Crop options carry provenance per option, not once for the payload: without
    // it, printing "Freshness unavailable" would misreport a data problem.
    if (payload.provenance) container.appendChild(metaRow(provenanceNotes(payload)));
    container.appendChild(cropOptionsCard(payload));
  }

  function activeContext() {
    var state = global.AgriqPanelState || {};
    return {
      field_id: state.activeFieldId || null,
      crop_cycle_id: state.activeCropCycleId || null,
    };
  }

  function numberField(id) {
    var node = document.getElementById(id);
    if (!node) return null;
    var raw = (node.value || "").trim();
    if (!raw) return null;
    var value = Number(raw);
    return isFinite(value) ? value : null;
  }

  /**
   * The farmer's own sale figures. A blank field is omitted entirely so the
   * backend keeps it unknown and withholds the net value — the panel never
   * supplies a zero, a yield or a freight rate of its own.
   */
  function saleContext() {
    var payload = activeContext();
    var quantity = numberField("marketQuantity");
    var rate = numberField("marketTransportRate");
    var freight = numberField("marketFreight");
    var inputCost = numberField("marketInputCost");
    var fee = numberField("marketMarketFee");
    if (quantity !== null) payload.quantity_quintals = quantity;
    if (rate !== null) payload.transport_rate_per_km_quintal = rate;
    if (freight !== null) payload.transport_cost_total = freight;
    if (inputCost !== null) payload.input_cost_total = inputCost;
    if (fee !== null) payload.market_fee_total = fee;
    return payload;
  }

  /** "Not stated" is a real answer, so it is left out rather than sent as false. */
  function withStorage(payload) {
    var node = document.getElementById("marketStorage");
    var value = node ? node.value : "";
    if (value === "yes") payload.storage_available = true;
    if (value === "no") payload.storage_available = false;
    return payload;
  }

  function run(button, loader, renderer, busyText) {
    if (!global.AgriqAPI) return;
    if (button) button.disabled = true;
    message(busyText);
    var container = document.getElementById("marketPanelBody");
    if (container) container.setAttribute("aria-busy", "true");
    loader().then(renderer).catch(function (error) {
      message(error && error.message ? error.message : "Market data is temporarily unavailable.", "market-error");
    }).then(function () {
      if (button) button.disabled = false;
    });
  }

  function loadOverview(button) {
    run(button, function () {
      return global.AgriqAPI.marketOverview(activeContext());
    }, renderOverview, "Loading official market records…");
  }

  function loadTiming(button) {
    run(button, function () {
      return global.AgriqAPI.marketSellHold(withStorage(activeContext()));
    }, renderTiming, "Assessing stored official records…");
  }

  function loadLogistics(button) {
    run(button, function () {
      return global.AgriqAPI.marketLogistics(saleContext());
    }, renderLogistics, "Comparing markets and checking cost completeness…");
  }

  function loadCropOptions(button) {
    run(button, function () {
      return global.AgriqAPI.marketCropOptions(activeContext());
    }, renderCropOptions, "Evaluating crops for your district…");
  }

  function setCropLabel(label) {
    var node = document.getElementById("marketPanelCrop");
    if (node && label) node.textContent = label;
  }

  function init() {
    var refresh = document.getElementById("marketRefresh");
    var timing = document.getElementById("marketSellHold");
    var options = document.getElementById("marketCropOptions");
    var logistics = document.getElementById("marketLogistics");
    if (refresh) refresh.addEventListener("click", function () { loadOverview(refresh); });
    if (timing) timing.addEventListener("click", function () { loadTiming(timing); });
    if (options) options.addEventListener("click", function () { loadCropOptions(options); });
    if (logistics) logistics.addEventListener("click", function () { loadLogistics(logistics); });
    if (!global.AgriqAPI || !global.AgriqAPI.farmerContext) return;

    global.AgriqAPI.farmerContext().then(function (payload) {
      // The endpoint answers {ok, context}; the context itself carries the field
      // and the active crop cycle (same shape the assistant panel consumes).
      var ctx = (payload && payload.context) || {};
      var field = ctx.field || {};
      var cycle = ctx.crop_cycle || {};
      global.AgriqPanelState = global.AgriqPanelState || {};
      global.AgriqPanelState.activeFieldId = field.id || global.AgriqPanelState.activeFieldId;
      global.AgriqPanelState.activeCropCycleId = cycle.id || global.AgriqPanelState.activeCropCycleId;
      if (cycle.crop) {
        setCropLabel(cycle.crop + (field.name ? " · " + field.name : ""));
        loadOverview(null);
      } else {
        setCropLabel(field.name || "");
        message("Register a crop cycle to see market intelligence for your crop.");
      }
    }).catch(function () {
      // A failed context read is not the same as "no crop cycle": say so instead
      // of telling a farmer who has one that they must register it.
      message("Your farm details could not be loaded, so market intelligence cannot run yet. "
        + "Reload the page to try again.", "market-error");
    });
  }

  global.MarketPanel = {
    init: init,
    loadOverview: loadOverview,
    loadTiming: loadTiming,
    loadCropOptions: loadCropOptions,
    loadLogistics: loadLogistics,
  };

  if (document.readyState !== "loading") {
    init();
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})(window);
