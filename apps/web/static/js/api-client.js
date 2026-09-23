/**
 * AGRIQ AI — API client.
 * Thin fetch wrappers for the assistant and live-weather endpoints.
 * The CSRF token is injected from the DOM (meta tag rendered by the server).
 */
(function (global) {
  "use strict";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  async function askAI(question, context) {
    var response = await fetch("/ask-ai", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify({ question: question, context: context || {} }),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.answer || "Assistant error");
    return data;
  }

  async function fetchLiveWeather(params) {
    var query = new URLSearchParams(params);
    var response = await fetch("/api/live-weather?" + query.toString());
    if (!response.ok) throw new Error("Weather unavailable");
    return response.json();
  }

  /** Phase 2: one Farm Copilot turn (versioned API). */
  async function copilotMessage(payload, compact) {
    var url = "/api/v1/copilot/messages" + (compact ? "?response_mode=compact" : "");
    var response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify(payload),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.answer || data.error || "Copilot error");
    return data;
  }

  /** Phase 2: feedback/outcome on a recommendation. */
  async function recommendationFeedback(recommendationId, payload) {
    var response = await fetch("/api/v1/recommendations/" + recommendationId + "/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify(payload),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "Feedback error");
    return data;
  }

  /** Phase 2: farmer context for the copilot panel chips. */
  async function farmerContext() {
    var response = await fetch("/api/farmer-context");
    if (!response.ok) throw new Error("Context unavailable");
    return response.json();
  }

  // --- Phase 3: voice endpoints -------------------------------------------

  async function voiceCapabilities() {
    var response = await fetch("/api/v1/voice/capabilities");
    if (!response.ok) throw new Error("Capabilities unavailable");
    return response.json();
  }

  async function voiceConsentStatus() {
    var response = await fetch("/api/v1/voice/consent");
    if (!response.ok) throw new Error("Consent status unavailable");
    return response.json();
  }

  async function voiceGiveConsent(payload) {
    var response = await fetch("/api/v1/voice/consent", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify(payload),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "Consent failed");
    return data;
  }

  async function voiceStartSession(language, fieldId, cropCycleId, retainAudio) {
    var response = await fetch("/api/v1/voice/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({
        language: language, field_id: fieldId || null,
        crop_cycle_id: cropCycleId || null, retain_audio: !!retainAudio,
      }),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not start voice session");
    return data;
  }

  async function voiceUploadAndTranscribe(blob, language, fieldId, cropCycleId) {
    var session = await voiceStartSession(language, fieldId, cropCycleId, false);
    var form = new FormData();
    form.append("audio", blob, "recording.webm");
    form.append("csrf_token", csrfToken());
    var upload = await fetch("/api/v1/voice/sessions/" + session.session.session_id + "/audio", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken() },
      body: form,
    });
    var uploadData = await upload.json();
    if (!upload.ok) throw new Error(uploadData.error || "Upload failed");
    var transcription = await fetch("/api/v1/voice/sessions/" + session.session.session_id + "/transcription");
    var transcriptData = await transcription.json();
    if (!transcriptData.session) transcriptData.session = session.session;
    return transcriptData;
  }

  async function voiceConfirmTranscript(sessionId, confirmedText, language) {
    var response = await fetch("/api/v1/voice/sessions/" + sessionId + "/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ confirmed_transcript: confirmedText, language: language }),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not confirm transcript");
    return data;
  }

  async function voiceAskCopilot(sessionId) {
    var response = await fetch("/api/v1/voice/sessions/" + sessionId + "/ask", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken() },
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "Assistant error");
    return data;
  }

  async function voiceSynthesise(messageId, language) {
    var response = await fetch("/api/v1/voice/synthesise", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ message_id: messageId, language: language }),
    });
    var data = await response.json();
    return { ok: response.ok, status: data.status, audio_id: data.audio_id,
             message: data.message, provider: data.provider };
  }

  async function voiceDeleteRecording(sessionId) {
    var response = await fetch("/api/v1/voice/sessions/" + sessionId + "/audio", {
      method: "DELETE",
      headers: { "X-CSRF-Token": csrfToken() },
    });
    return response.ok;
  }

  // --- Phase 4: crop-image endpoints ---------------------------------------

  async function imageCapabilities() {
    var response = await fetch("/api/v1/crop-images/capabilities");
    if (!response.ok) throw new Error("Image capabilities unavailable");
    return response.json();
  }

  async function analyseCropImage(file, crop) {
    var form = new FormData();
    form.append("image", file, file.name || "leaf.jpg");
    form.append("crop", crop || "rice");
    form.append("csrf_token", csrfToken());
    var response = await fetch("/api/v1/crop-images/analyse", {
      method: "POST",
      body: form,
    });
    var data = await response.json();
    if (!response.ok) {
      // Keep the canonical farmer-facing message; never raw provider errors.
      return { ok: false, error: data.error || "AGRIQ could not analyse this photo." };
    }
    return data;
  }

  async function sendImageFeedback(analysisId, farmerFeedback) {
    var response = await fetch("/api/v1/crop-images/analyses/" + analysisId + "/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ farmer_feedback: farmerFeedback }),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "Feedback failed");
    return data;
  }

  async function requestImageExpertReview(analysisId) {
    var response = await fetch("/api/v1/crop-images/analyses/" + analysisId + "/request-expert-review", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({}),
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  global.AgriqAPI = {
    askAI: askAI,
    fetchLiveWeather: fetchLiveWeather,
    copilotMessage: copilotMessage,
    recommendationFeedback: recommendationFeedback,
    farmerContext: farmerContext,
    imageCapabilities: imageCapabilities,
    analyseCropImage: analyseCropImage,
    sendImageFeedback: sendImageFeedback,
    requestImageExpertReview: requestImageExpertReview,
    voiceCapabilities: voiceCapabilities,
    voiceConsentStatus: voiceConsentStatus,
    voiceGiveConsent: voiceGiveConsent,
    voiceStartSession: voiceStartSession,
    voiceUploadAndTranscribe: voiceUploadAndTranscribe,
    voiceConfirmTranscript: voiceConfirmTranscript,
    voiceAskCopilot: voiceAskCopilot,
    voiceSynthesise: voiceSynthesise,
    voiceDeleteRecording: voiceDeleteRecording,
    csrfToken: csrfToken,
  };
})(window);
