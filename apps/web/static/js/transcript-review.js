/**
 * AGRIQ AI — Transcript review & voice ask flow (Phase 3).
 *
 * Pipeline: submit recording → show RAW transcript with provider confidence
 * (or "Confidence not provided.") → farmer edits → confirm → ask the
 * existing copilot → render the answer + "Listen" control.
 * An uncertain transcript is never auto-submitted; confirmation is required.
 */
(function (global) {
  "use strict";

  var state = { sessionId: null, transcriptId: null, confirmedText: null, language: "en-IN" };

  function el(id) { return document.getElementById(id); }

  function setStatus(text) {
    var node = el("voiceStatus");
    if (node) node.textContent = text || "";
  }

  async function submitRecording(blob, language, fieldId, cropCycleId) {
    state.language = language;
    setStatus("Uploading recording…");
    try {
      var result = await global.AgriqAPI.voiceUploadAndTranscribe(blob, language, fieldId, cropCycleId);
      if (result.status === "unavailable") {
        setStatus(result.message || "We could not reliably understand this recording. Please try again or type your question.");
        return null;
      }
      state.sessionId = result.session.session_id;
      showTranscriptReview(result.transcript);
      return result;
    } catch (error) {
      setStatus(error.message || "Upload failed. Your recording stays queued and text input still works.");
      throw error;
    }
  }

  function showTranscriptReview(transcript) {
    var card = el("voiceTranscriptCard");
    if (!card || !transcript) return;
    card.hidden = false;
    var textarea = el("voiceTranscriptEdit");
    textarea.value = transcript.raw_transcript || "";
    textarea.setAttribute("lang", state.language);
    var confidenceNode = el("voiceTranscriptConfidence");
    if (transcript.confidence && transcript.confidence.available) {
      confidenceNode.textContent = "Recognition confidence: " +
        Math.round(transcript.confidence.value * 100) + "% (from provider)";
    } else {
      confidenceNode.textContent = "Confidence not provided.";
    }
    setStatus("Please review the transcript. Edit if needed, then confirm.");
  }

  async function confirmAndAsk() {
    var textarea = el("voiceTranscriptEdit");
    var confirmed = (textarea.value || "").trim();
    if (!confirmed) {
      setStatus("Type or confirm your question first.");
      return;
    }
    setStatus("Confirming transcript…");
    try {
      var confirmed = await global.AgriqAPI.voiceConfirmTranscript(state.sessionId, confirmed, state.language);
      state.confirmedText = confirmed.transcript.corrected_transcript;
      setStatus("Asking the AGRIQ assistant…");
      var answer = await global.AgriqAPI.voiceAskCopilot(state.sessionId);
      renderAnswer(answer);
    } catch (error) {
      setStatus(error.message || "Something went wrong. You can also type your question instead.");
    }
  }

  function renderAnswer(answer) {
    var chatBody = el("chatBody");
    var copilot = answer.copilot || {};
    var text = copilot.answer || "No answer was generated. Please try again or type your question.";
    var div = document.createElement("div");
    div.className = "bot-message";
    div.textContent = text;
    if (answer.vocabulary_suggestion) {
      var sug = document.createElement("div");
      sug.className = "voice-vocab-suggestion";
      sug.textContent = "Did you mean: " + answer.vocabulary_suggestion.suggestion + "?";
      div.appendChild(sug);
    }
    var listen = document.createElement("button");
    listen.type = "button";
    listen.className = "ghost-btn voice-listen-btn";
    listen.textContent = "🔊 Listen";
    listen.setAttribute("aria-label", "Listen to this answer");
    listen.addEventListener("click", function () {
      global.AgriqAudioPlayer.playAnswer(copilot.message_id || copilot.assistant_message_id, state.language, listen);
    });
    div.appendChild(listen);
    chatBody.appendChild(div);
    chatBody.scrollTop = chatBody.scrollHeight;
    if (global.AgriqAssistant && copilot.confidence) {
      // Reuse the text-mode answer decorations where useful.
      var why = document.createElement("details");
      why.className = "copilot-why";
      var summary = document.createElement("summary");
      summary.textContent = "Why this advice?";
      why.appendChild(summary);
      var ul = document.createElement("ul");
      (copilot.reasons || []).forEach(function (reason) {
        var li = document.createElement("li");
        li.textContent = reason;
        ul.appendChild(li);
      });
      why.appendChild(ul);
      div.appendChild(why);
    }
    setStatus("Answer ready. You can listen to it or continue the conversation.");
  }

  function reset() {
    state = { sessionId: null, transcriptId: null, confirmedText: null, language: state.language };
    var card = el("voiceTranscriptCard");
    if (card) card.hidden = true;
  }

  global.AgriqTranscriptReview = {
    submitRecording: submitRecording,
    confirmAndAsk: confirmAndAsk,
    reset: reset,
    state: state,
  };
})(window);
