/**
 * AGRIQ Phase 4 — crop-image screening UI.
 *
 * Progressive panel in the assistant area. Talks only to /api/v1/crop-images
 * endpoints (CSRF handled by api-client). Never fabricates a result: every
 * state (completed / rejected / unavailable) is rendered from the server's
 * own response, with the canonical unavailable message when the model or
 * service is not available.
 */
(function () {
  "use strict";

  var els = {};

  function ready() {
    els = {
      area: document.getElementById("imageArea"),
      status: document.getElementById("imageServiceStatus"),
      crop: document.getElementById("imageCropSelect"),
      file: document.getElementById("imageFileInput"),
      preview: document.getElementById("imagePreview"),
      card: document.getElementById("imageResultCard"),
      resultStatus: document.getElementById("imageResultStatus"),
      resultGuidance: document.getElementById("imageResultGuidance"),
      resultPredictions: document.getElementById("imageResultPredictions"),
      feedbackBtn: document.getElementById("imageFeedbackBtn"),
      expertBtn: document.getElementById("imageExpertBtn"),
    };
    if (!els.area || els.area.dataset.bound === "1") return;
    els.area.dataset.bound = "1";

    els.file.addEventListener("change", onFileSelected);
    if (els.feedbackBtn) els.feedbackBtn.addEventListener("click", onFeedback);
    if (els.expertBtn) els.expertBtn.addEventListener("click", onExpertReview);

    // Probe capability once so farmers see an honest state before uploading.
    AGRIQ.api.imageCapabilities().then(function (res) {
      if (res && res.ok && res.image_analysis_available === false) {
        setServiceStatus("Image analysis is not currently available.");
        els.file.disabled = true;
      } else if (res && res.ok) {
        setServiceStatus("");
      }
    }).catch(function () { /* probe failure is silent; upload reports errors */ });
  }

  function setServiceStatus(text) {
    if (els.status) els.status.textContent = text || "";
  }

  function onFileSelected() {
    var file = els.file.files && els.file.files[0];
    if (!file) return;
    resetResult();
    if (file.size > 5 * 1024 * 1024) {
      showResult("The photo is too large (maximum 5 MB). Please choose a smaller photo.", []);
      return;
    }
    var url = URL.createObjectURL(file);
    els.preview.src = url;
    els.preview.hidden = false;
    submit(file);
  }

  function submit(file) {
    setServiceStatus("Checking your photo…");
    var crop = els.crop ? els.crop.value : "rice";
    AGRIQ.api.analyseCropImage(file, crop).then(function (res) {
      setServiceStatus("");
      if (!res || !res.ok) {
        showResult(res && res.error ? res.error : "AGRIQ could not analyse this photo. Please try again.", []);
        return;
      }
      renderAnalysis(res.analysis || {});
    }).catch(function () {
      setServiceStatus("");
      showResult("AGRIQ could not analyse this photo. Please try again.", []);
    });
  }

  function renderAnalysis(a) {
    var lines = [];
    if (a.status === "unavailable") {
      showResult(a.message || "Image analysis is not currently available.", []);
      return;
    }
    if (a.status === "rejected") {
      var guidance = (a.image_quality && a.image_quality.guidance) || a.guidance || [];
      showResult(a.message || "AGRIQ could not identify this condition reliably. Please retake the image or consult an agriculture expert.", guidance);
      return;
    }

    if (a.abstained) {
      lines.push("AGRIQ is not confident enough to suggest a possible condition from this photo.");
    } else if (a.predictions && a.predictions.length) {
      var p = a.predictions[0];
      lines.push((p.display_name || p.condition) + " — possible condition" +
        (a.confidence_category ? " (" + String(a.confidence_category).replace("_", " ") + " confidence)" : ""));
    } else {
      lines.push("AGRIQ could not identify this condition reliably.");
    }
    var explanation = a.explanation || [];
    var limitations = a.limitations || [];
    showResult(lines.join(" "), explanation.concat(limitations), a);
  }

  function showResult(text, guidanceLines, analysis) {
    els.card.hidden = false;
    els.resultStatus.textContent = text;
    els.resultGuidance.innerHTML = "";
    (guidanceLines || []).forEach(function (line) {
      var li = document.createElement("li");
      li.textContent = line;
      els.resultGuidance.appendChild(li);
    });
    els.resultPredictions.innerHTML = "";
    els.resultPredictions.hidden = true;
    var hasAnalysis = !!(analysis && analysis.analysis_id);
    if (els.feedbackBtn) els.feedbackBtn.hidden = !hasAnalysis;
    if (els.expertBtn) els.expertBtn.hidden = !hasAnalysis;
    els.card.dataset.analysisId = hasAnalysis ? String(analysis.analysis_id) : "";
  }

  function resetResult() {
    if (els.card) {
      els.card.hidden = true;
      els.card.dataset.analysisId = "";
    }
    if (els.resultStatus) els.resultStatus.textContent = "";
    if (els.resultGuidance) els.resultGuidance.innerHTML = "";
    if (els.preview) els.preview.hidden = true;
  }

  function currentAnalysisId() {
    return els.card && els.card.dataset.analysisId ? els.card.dataset.analysisId : null;
  }

  function onFeedback() {
    var id = currentAnalysisId();
    if (!id) return;
    var note = window.prompt("Tell AGRIQ briefly: was this result helpful? What did you see in the field?");
    if (!note) return;
    AGRIQ.api.sendImageFeedback(id, note).then(function (res) {
      if (res && res.ok) {
        if (els.feedbackBtn) { els.feedbackBtn.textContent = "Thank you — noted"; els.feedbackBtn.disabled = true; }
      }
    }).catch(function () { /* errors already surfaced by api-client */ });
  }

  function onExpertReview() {
    var id = currentAnalysisId();
    if (!id) return;
    AGRIQ.api.requestImageExpertReview(id).then(function (res) {
      if (res && res.ok) {
        if (els.expertBtn) { els.expertBtn.textContent = "Expert review requested"; els.expertBtn.disabled = true; }
      }
    }).catch(function () { /* errors already surfaced by api-client */ });
  }

  document.addEventListener("DOMContentLoaded", ready);
  if (document.readyState !== "loading") ready();
})();
