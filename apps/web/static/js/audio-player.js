/**
 * AGRIQ AI — Answer audio player (Phase 3).
 *
 * Requests TTS synthesis for an owned answer, streams the private audio
 * endpoint, and exposes play/pause/resume. TTS failure keeps the written
 * answer and shows "Audio playback is currently unavailable." — never an
 * empty audio file, never a fake success.
 */
(function (global) {
  "use strict";

  var currentAudio = null;

  function el(id) { return document.getElementById(id); }

  function stopCurrent() {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
  }

  async function playAnswer(messageId, language, button) {
    if (!messageId) return;
    if (button) {
      if (button.dataset.state === "playing") {   // pause/resume toggle
        if (currentAudio && !currentAudio.paused) {
          currentAudio.pause();
          button.dataset.state = "paused";
          button.textContent = "▶ Resume";
        } else if (currentAudio) {
          currentAudio.play();
          button.dataset.state = "playing";
          button.textContent = "⏸ Pause";
        }
        return;
      }
      button.textContent = "… Loading audio";
    }
    stopCurrent();
    try {
      var result = await global.AgriqAPI.voiceSynthesise(messageId, language);
      if (!result.ok || result.status !== "completed") {
        showUnavailable(button);
        return;
      }
      var audio = new global.Audio("/api/v1/voice/audio/" + result.audio_id);
      currentAudio = audio;
      audio.addEventListener("ended", function () {
        if (button) { button.dataset.state = ""; button.textContent = "🔊 Listen"; }
      });
      await audio.play();
      if (button) { button.dataset.state = "playing"; button.textContent = "⏸ Pause"; }
    } catch (error) {
      showUnavailable(button);
    }
  }

  function showUnavailable(button) {
    if (button) { button.textContent = "🔊 Listen"; button.dataset.state = ""; }
    var chatBody = el("chatBody");
    if (chatBody) {
      var note = document.createElement("div");
      note.className = "voice-tts-unavailable";
      note.textContent = "Audio playback is currently unavailable.";
      chatBody.appendChild(note);
      chatBody.scrollTop = chatBody.scrollHeight;
    }
  }

  global.AgriqAudioPlayer = { playAnswer: playAnswer, stopCurrent: stopCurrent };
})(window);
