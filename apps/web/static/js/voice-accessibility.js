/**
 * AGRIQ AI — Voice accessibility (Phase 3).
 *
 * - Every voice control has an accessible name (visible text or aria-label).
 * - Recording state is announced to screen readers via a polite live region.
 * - Status is conveyed by text + icon, never colour alone.
 * - prefers-reduced-motion is respected (no pulsing animations).
 * - Keyboard: Enter/Space on the mic button, Escape stops recording.
 */
(function (global) {
  "use strict";

  function init() {
    var mic = document.getElementById("voiceMicBtn");
    if (mic && !mic.getAttribute("aria-label")) {
      mic.setAttribute("aria-label", "Record your question with the microphone");
    }
    var submit = document.getElementById("voiceSubmitBtn");
    if (submit) submit.setAttribute("aria-label", "Submit recording for transcription");
    var del = document.getElementById("voiceDeleteBtn");
    if (del) del.setAttribute("aria-label", "Delete the recording without sending it");
    var confirmBtn = document.getElementById("voiceConfirmAskBtn");
    if (confirmBtn) confirmBtn.setAttribute("aria-label", "Confirm transcript and ask the assistant");

    // Polite live region for status changes.
    var status = document.getElementById("voiceStatus");
    if (status) {
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
    }

    if (mic) {
      mic.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && mic.getAttribute("aria-pressed") === "true") {
          event.preventDefault();
          if (global.AgriqVoiceRecorder) global.AgriqVoiceRecorder.stop();
        }
      });
    }

    // Reduced motion: disable the recording pulse.
    try {
      if (global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        document.documentElement.classList.add("voice-reduced-motion");
      }
    } catch (error) { /* matchMedia unavailable */ }
  }

  function announce(text) {
    var status = document.getElementById("voiceStatus");
    if (status) status.textContent = text;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.AgriqVoiceAccessibility = { init: init, announce: announce };
})(window);
