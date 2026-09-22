/**
 * AGRIQ AI — Voice recorder (Phase 3).
 *
 * Captures audio with MediaRecorder (progressive enhancement — the text
 * input always remains). Enforces the consent gate, shows a recording
 * timer, allows preview/delete before submit, and hands the blob to the
 * upload queue. Status is conveyed by text + icon, never colour alone.
 */
(function (global) {
  "use strict";

  var state = {
    recording: false,
    mediaRecorder: null,
    chunks: [],
    blob: null,
    timerId: null,
    seconds: 0,
    stream: null,
    language: "en-IN",
    consentChecked: false,
  };
  var MAX_SECONDS = 60;

  function el(id) { return document.getElementById(id); }

  function setStatus(text) {
    var node = el("voiceStatus");
    if (node) node.textContent = text;
  }

  function setTimer(seconds) {
    var node = el("voiceTimer");
    if (node) node.textContent = formatSeconds(seconds);
  }

  function formatSeconds(total) {
    var m = Math.floor(total / 60);
    var s = total % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function isSupported() {
    return !!(global.navigator && global.navigator.mediaDevices &&
              global.navigator.mediaDevices.getUserMedia &&
              global.MediaRecorder);
  }

  async function ensureConsent() {
    if (state.consentChecked) return true;
    try {
      var res = await global.AgriqAPI.voiceConsentStatus();
      if (res.consent && res.consent.is_active) {
        state.consentChecked = true;
        return true;
      }
    } catch (e) { /* fallthrough to prompt */ }
    var accepted = global.confirm(
      "Voice privacy notice:\n\n" +
      "• Your recording will be sent to the configured speech service to transcribe your question.\n" +
      "• Recordings are deleted after transcription (default).\n" +
      "• Transcripts are stored with your conversation; you can edit them before sending.\n" +
      "• Audio is never used for training without separate explicit consent.\n\n" +
      "Do you accept and want to use voice input?"
    );
    if (!accepted) return false;
    var saved = await global.AgriqAPI.voiceGiveConsent({
      speech_provider_processing_allowed: true,
      evaluation_use_allowed: false,
      audio_retention_allowed: false,
    });
    state.consentChecked = !!(saved.consent && saved.consent.is_active);
    return state.consentChecked;
  }

  async function startRecording() {
    if (state.recording) return;
    if (!isSupported()) {
      setStatus("Voice recording is not supported on this device. Please type your question.");
      return;
    }
    if (!(await ensureConsent())) return;

    var capabilities = await global.AgriqAPI.voiceCapabilities().catch(function () { return null; });
    if (capabilities && capabilities.languages) {
      var lang = state.language;
      if (capabilities.languages[lang] && !capabilities.languages[lang].asr_available) {
        setStatus("Speech recognition for the selected language is unavailable right now. You can still type your question.");
      }
    }

    try {
      state.stream = await global.navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      setStatus("Microphone permission was not granted. Please allow the microphone or type your question.");
      return;
    }
    state.chunks = [];
    state.blob = null;
    state.seconds = 0;
    try {
      state.mediaRecorder = new MediaRecorder(state.stream);
    } catch (error) {
      setStatus("Voice recording could not start. Please type your question.");
      stopStream();
      return;
    }
    state.mediaRecorder.ondataavailable = function (event) {
      if (event.data && event.data.size) state.chunks.push(event.data);
    };
    state.mediaRecorder.onstop = function () {
      state.blob = new Blob(state.chunks, { type: state.mediaRecorder.mimeType || "audio/webm" });
      showPreview();
    };
    state.mediaRecorder.start();
    state.recording = true;
    setStatus("Recording… (speak now)");
    setControls();
    state.timerId = global.setInterval(function () {
      state.seconds += 1;
      setTimer(state.seconds);
      if (state.seconds >= MAX_SECONDS) stopRecording();  // server limit mirrored client-side
    }, 1000);
  }

  function stopRecording() {
    if (!state.recording) return;
    state.recording = false;
    if (state.timerId) global.clearInterval(state.timerId);
    if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
      state.mediaRecorder.stop();
    }
    stopStream();
    setStatus("Recording stopped.");
    setControls();
  }

  function stopStream() {
    if (state.stream) {
      state.stream.getTracks().forEach(function (track) { track.stop(); });
      state.stream = null;
    }
  }

  function showPreview() {
    var preview = el("voicePreview");
    if (preview && state.blob) {
      preview.src = global.URL.createObjectURL(state.blob);
      preview.hidden = false;
    }
    var submit = el("voiceSubmitBtn");
    if (submit) submit.disabled = false;
    var del = el("voiceDeleteBtn");
    if (del) del.disabled = false;
  }

  function discardRecording() {
    state.blob = null;
    state.chunks = [];
    setTimer(0);
    var preview = el("voicePreview");
    if (preview) { preview.hidden = true; preview.removeAttribute("src"); }
    var submit = el("voiceSubmitBtn");
    if (submit) submit.disabled = true;
    var del = el("voiceDeleteBtn");
    if (del) del.disabled = true;
    setStatus("Recording deleted.");
  }

  function setControls() {
    var mic = el("voiceMicBtn");
    if (mic) {
      mic.setAttribute("aria-pressed", state.recording ? "true" : "false");
      mic.textContent = state.recording ? "⏹ Stop" : "🎤 Record";
    }
  }

  function setLanguage(code) { state.language = code || "en-IN"; }

  function reset() {
    stopRecording();
    discardRecording();
  }

  global.AgriqVoiceRecorder = {
    start: startRecording,
    stop: stopRecording,
    discard: discardRecording,
    setLanguage: setLanguage,
    getBlob: function () { return state.blob; },
    getLanguage: function () { return state.language; },
    isSupported: isSupported,
  };
})(window);
