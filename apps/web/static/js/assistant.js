/**
 * AGRIQ AI — Assistant chat panel.
 *
 * Phase 2 upgrade: farmer mode uses the versioned copilot API
 * (context indicator chips, language selector, low-data mode, source
 * badges, confidence level, "Why this advice?" details, missing-information
 * notice, expert-confirmation warning and recommendation feedback buttons).
 * Student mode keeps the original /ask-ai flow unchanged.
 */
(function (global) {
  "use strict";

  var copilotState = { conversationId: null, lastRecommendationId: null, contextLoaded: false };

  function addMessage(text, type) {
    var body = document.getElementById("chatBody");
    var div = document.createElement("div");
    div.className = type === "user" ? "user-message" : "bot-message";
    div.textContent = text;
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  function quickAskAI(text) {
    var input = document.getElementById("chatQuestion");
    input.value = text;
    askAGRIQAI();
  }

  function getStudentContext() {
    var form = document.getElementById("studentStudyForm");
    if (!form) return {};
    var data = new FormData(form);
    var context = {};
    for (var pair of data.entries()) context[pair[0]] = pair[1];
    return context;
  }

  function getFarmerContext() {
    return {
      crop: (document.getElementById("cropInput") || {}).value || "Rice",
      district: (document.getElementById("districtSelect") || {}).value || "Cuttack",
      growth_stage: (document.getElementById("growthStageSelect") || {}).value || "Vegetative",
      field_condition: (document.getElementById("fieldConditionSelect") || {}).value || "Normal field",
    };
  }

  function isFarmerMode() {
    var boot = global.AgriqBoot || {};
    return boot.userMode !== "student";
  }

  // --- Phase 2 copilot panel -------------------------------------------------

  function setChip(id, text) {
    var chip = document.getElementById(id);
    if (!chip) return;
    chip.textContent = text || "";
    chip.hidden = !text;
  }

  function loadContextChips() {
    if (!isFarmerMode() || copilotState.contextLoaded) return;
    global.AgriqAPI.farmerContext().then(function (result) {
      copilotState.contextLoaded = true;
      var context = result.context || {};
      var cycle = context.crop_cycle || {};
      var weather = context.weather || {};
      var chips = document.getElementById("copilotContextChips");
      if (chips) chips.hidden = false;
      setChip("copilotCropChip", cycle.crop ? "Crop: " + cycle.crop : "");
      setChip("copilotStageChip", cycle.effective_stage ? "Stage: " + cycle.effective_stage : "Stage: not confirmed");
      var freshness = weather.available ? (weather.live ? "Weather: live" : (weather.stale ? "Weather: stale" : "Weather: cached")) : "Weather: unavailable";
      setChip("copilotWeatherChip", freshness);
    }).catch(function () { /* context chips are best-effort */ });
  }

  function sourceBadges(sources) {
    if (!sources || !sources.length) return null;
    var wrap = document.createElement("div");
    wrap.className = "copilot-sources";
    sources.forEach(function (source) {
      var badge = document.createElement("span");
      badge.className = "pill copilot-source-badge";
      badge.textContent = (source.organisation || source.title || "Source");
      badge.title = (source.title || "") + (source.section ? " — " + source.section : "") +
        (source.publication_date ? " (" + source.publication_date + ")" : "");
      wrap.appendChild(badge);
    });
    return wrap;
  }

  function confidenceLine(confidence) {
    if (!confidence) return null;
    var line = document.createElement("div");
    line.className = "copilot-confidence copilot-confidence-" + (confidence.level || "low");
    line.textContent = "Confidence: " + (confidence.level || "low");
    if (confidence.basis) line.title = confidence.basis;
    return line;
  }

  function whyDetails(payload) {
    var reasons = payload.reasons || [];
    var evidence = payload.evidence || [];
    var missing = payload.missing_information || [];
    if (!reasons.length && !evidence.length && !missing.length) return null;
    var details = document.createElement("details");
    details.className = "copilot-why";
    var summary = document.createElement("summary");
    summary.textContent = "Why this advice?";
    details.appendChild(summary);
    var list = document.createElement("ul");
    reasons.forEach(function (reason) {
      var item = document.createElement("li");
      item.textContent = reason;
      list.appendChild(item);
    });
    evidence.forEach(function (item) {
      var li = document.createElement("li");
      li.textContent = "Evidence: " + (item.source || "source") +
        (item.observed_or_retrieved_at ? " (" + item.observed_or_retrieved_at + ")" : "");
      list.appendChild(li);
    });
    missing.forEach(function (itemText) {
      var li = document.createElement("li");
      li.textContent = "Missing: " + itemText;
      list.appendChild(li);
    });
    details.appendChild(list);
    return details;
  }

  function feedbackControls(recommendationId) {
    if (!recommendationId) return null;
    var wrap = document.createElement("div");
    wrap.className = "copilot-feedback";
    var label = document.createElement("span");
    label.textContent = "Did you take this action?";
    wrap.appendChild(label);
    [["Completed", "completed"], ["Skipped", "skipped"], ["Need help", "needs_help"]].forEach(function (pair) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "ghost-btn copilot-feedback-btn";
      button.textContent = pair[0];
      button.addEventListener("click", function () {
        global.AgriqAPI.recommendationFeedback(recommendationId, { status: pair[1] })
          .then(function () {
            wrap.textContent = "Recorded. Thank you — your outcome stays in your farm history.";
          })
          .catch(function () {
            wrap.textContent = "Could not record feedback. Please try again.";
          });
      });
      wrap.appendChild(button);
    });
    return wrap;
  }

  function renderCopilotAnswer(payload) {
    var body = document.getElementById("chatBody");
    var message = addMessage(payload.answer || "No answer generated.", "bot");
    copilotState.conversationId = payload.conversation_id || copilotState.conversationId;
    copilotState.lastRecommendationId = payload.recommendation_id || copilotState.lastRecommendationId;

    if (payload.requires_expert_confirmation) {
      var warning = document.createElement("div");
      warning.className = "copilot-expert-warning";
      warning.textContent = "⚠ Expert confirmation is advised. " +
        ((payload.escalation && payload.escalation.handover_message) || "");
      message.appendChild(warning);
    }
    var sources = sourceBadges(payload.sources);
    if (sources) message.appendChild(sources);
    var confidence = confidenceLine(payload.confidence);
    if (confidence) message.appendChild(confidence);
    var why = whyDetails(payload);
    if (why) message.appendChild(why);
    var feedback = feedbackControls(payload.recommendation_id);
    if (feedback) message.appendChild(feedback);
    body.scrollTop = body.scrollHeight;
  }

  async function askCopilot(question) {
    var language = (document.getElementById("copilotLanguage") || {}).value || "en";
    var compact = !!(document.getElementById("copilotCompactMode") || {}).checked;
    var payload = { question: question, language: language };
    if (copilotState.conversationId) payload.conversation_id = copilotState.conversationId;
    var fieldSel = document.getElementById("farmDataFieldSelect");
    if (fieldSel && fieldSel.value) payload.field_id = fieldSel.value;

    try {
      var result = await global.AgriqAPI.copilotMessage(payload, compact);
      renderCopilotAnswer(result);
    } catch (error) {
      addMessage(error.message || "The AI assistant is temporarily unavailable.", "bot");
    }
  }

  // --- Legacy /ask-ai flow (student mode + fallback) --------------------------

  async function askAGRIQAI() {
    var input = document.getElementById("chatQuestion");
    var question = input.value.trim();
    if (!question) return;

    addMessage(question, "user");
    input.value = "";

    if (isFarmerMode()) {
      loadContextChips();
      await askCopilot(question);
      return;
    }

    try {
      var boot = global.AgriqBoot || {};
      var context = boot.userMode === "student" ? getStudentContext() : getFarmerContext();
      var data = await global.AgriqAPI.askAI(question, context);
      addMessage(data.answer || "No answer generated.", "bot");
    } catch (error) {
      addMessage("Assistant is temporarily unavailable. Please try again.", "bot");
    }
  }

  function bindKeyboard() {
    document.addEventListener("keydown", function (e) {
      var input = document.getElementById("chatQuestion");
      if (e.key === "Enter" && document.activeElement === input) {
        askAGRIQAI();
      }
    });
  }

  global.AgriqAssistant = {
    addMessage: addMessage,
    quickAskAI: quickAskAI,
    ask: askAGRIQAI,
    bindKeyboard: bindKeyboard,
    loadContextChips: loadContextChips,
  };
})(window);
