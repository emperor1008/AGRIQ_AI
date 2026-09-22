/**
 * AGRIQ AI — Voice UI bindings (Phase 3).
 * Connects the panel controls to the recorder, queue and review modules.
 * Only active in farmer mode; the text input is never replaced.
 */
(function (global) {
  "use strict";

  function el(id) { return document.getElementById(id); }

  function farmerMode() {
    var boot = global.AgriqBoot || {};
    return boot.userMode !== "student";
  }

  function init() {
    if (!farmerMode()) return;
    if (global.AgriqVoiceQueue) global.AgriqVoiceQueue.init();

    var langSelect = el("voiceLanguage");
    if (langSelect) {
      langSelect.addEventListener("change", function () {
        if (global.AgriqVoiceRecorder) global.AgriqVoiceRecorder.setLanguage(langSelect.value);
      });
    }

    var mic = el("voiceMicBtn");
    if (mic) {
      mic.addEventListener("click", function () {
        if (!global.AgriqVoiceRecorder) return;
        if (mic.getAttribute("aria-pressed") === "true") {
          global.AgriqVoiceRecorder.stop();
        } else {
          global.AgriqVoiceRecorder.start();
        }
      });
    }

    var submit = el("voiceSubmitBtn");
    if (submit) {
      submit.addEventListener("click", async function () {
        var recorder = global.AgriqVoiceRecorder;
        var blob = recorder ? recorder.getBlob() : null;
        if (!blob) return;
        submit.disabled = true;
        try {
          if (global.navigator.onLine) {
            await global.AgriqTranscriptReview.submitRecording(
              blob, recorder.getLanguage(),
              (el("farmDataFieldSelect") || {}).value || null, null
            );
            recorder.discard();
          } else {
            global.AgriqVoiceQueue.enqueue(blob, recorder.getLanguage(), null, null);
            recorder.discard();
          }
        } catch (error) {
          // Network failure mid-upload: queue locally (labelled QUEUED).
          global.AgriqVoiceQueue.enqueue(blob, recorder.getLanguage(), null, null);
          recorder.discard();
        }
      });
    }

    var del = el("voiceDeleteBtn");
    if (del) {
      del.addEventListener("click", function () {
        if (global.AgriqVoiceRecorder) global.AgriqVoiceRecorder.discard();
      });
    }

    var confirmAsk = el("voiceConfirmAskBtn");
    if (confirmAsk) {
      confirmAsk.addEventListener("click", function () {
        if (global.AgriqTranscriptReview) global.AgriqTranscriptReview.confirmAndAsk();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
