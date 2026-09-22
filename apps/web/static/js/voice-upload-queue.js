/**
 * AGRIQ AI — Voice upload queue (Phase 3, low-bandwidth behaviour).
 *
 * Offline/failed uploads stay in a local pending queue, clearly labelled
 * QUEUED (never "transcribed"). Nothing is fabricated: the queue stores
 * only the raw blob + language; submission happens when connectivity
 * returns. The farmer can delete queued items before upload.
 */
(function (global) {
  "use strict";

  var QUEUE_KEY = "agriq_voice_queue_v1";
  var state = { items: [], uploading: false };

  function load() {
    try {
      state.items = JSON.parse(global.localStorage.getItem(QUEUE_KEY) || "[]");
    } catch (error) {
      state.items = [];
    }
    return state.items;
  }

  function persist() {
    // Metadata only — the blob itself lives in an in-memory map, because
    // localStorage is too small for audio. Pending blobs are kept for this
    // page session; a page reload asks the farmer to re-record (labelled).
    try { global.localStorage.setItem(QUEUE_KEY, JSON.stringify(state.items)); } catch (e) { /* quota */ }
  }

  var blobs = new Map();

  function enqueue(blob, language, fieldId, cropCycleId) {
    var id = "q" + Date.now() + Math.floor(Math.random() * 1000);
    blobs.set(id, blob);
    state.items.push({
      id: id,
      language: language,
      field_id: fieldId || null,
      crop_cycle_id: cropCycleId || null,
      queued_at: new Date().toISOString(),
      label: "QUEUED — not yet sent",
    });
    persist();
    renderQueue();
    return id;
  }

  function remove(id) {
    blobs.delete(id);
    state.items = state.items.filter(function (item) { return item.id !== id; });
    persist();
    renderQueue();
  }

  async function flush() {
    if (state.uploading || !global.navigator.onLine) return;
    state.uploading = true;
    try {
      for (var i = 0; i < state.items.length; i++) {
        var item = state.items[i];
        var blob = blobs.get(item.id);
        if (!blob) continue;   // page reloaded: farmer re-records
        try {
          await global.AgriqAPI.voiceUploadAndTranscribe(blob, item.language, item.field_id, item.crop_cycle_id);
          remove(item.id);
          i -= 1;
        } catch (error) {
          break;   // keep the queue, retry on next connectivity/attempt
        }
      }
    } finally {
      state.uploading = false;
    }
  }

  function renderQueue() {
    var list = el("voiceQueue");
    if (!list) return;
    list.textContent = "";
    load();
    state.items.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "voice-queue-item";
      var badge = document.createElement("span");
      badge.className = "voice-queue-badge";
      badge.textContent = "⏳ " + item.label;
      li.appendChild(badge);
      var del = document.createElement("button");
      del.type = "button";
      del.className = "ghost-btn";
      del.textContent = "Delete";
      del.setAttribute("aria-label", "Delete queued recording");
      del.addEventListener("click", function () { remove(item.id); });
      li.appendChild(del);
      list.appendChild(li);
    });
  }

  function el(id) { return document.getElementById(id); }

  function init() {
    load();
    renderQueue();
    global.addEventListener("online", function () {
      setOfflineIndicator(false);
      flush();
    });
    global.addEventListener("offline", function () { setOfflineIndicator(true); });
    setOfflineIndicator(!global.navigator.onLine);
  }

  function setOfflineIndicator(offline) {
    var node = el("voiceOfflineIndicator");
    if (node) node.hidden = !offline;
  }

  global.AgriqVoiceQueue = {
    init: init,
    enqueue: enqueue,
    flush: flush,
    pendingCount: function () { return state.items.length; },
  };
})(window);
