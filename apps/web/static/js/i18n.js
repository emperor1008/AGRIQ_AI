/**
 * AGRIQ AI — browser i18n helper (Phase 7.2).
 *
 * One translation entry point on the client, fed by the same JSON catalogs the
 * server renders with (window.AGRIQ_I18N, written by base.html). Keys are
 * dotted paths; a missing key falls back to the key itself, exactly like the
 * server, so a new string can never render as "undefined".
 *
 * Interface strings only: authoritative agricultural text is never translated
 * in the browser — it comes from the knowledge API together with its source
 * language and review state.
 */
(function (global) {
  "use strict";

  var boot = global.AGRIQ_I18N || { lang: "en", status: "source_language", messages: {} };

  function format(text, params) {
    if (!params) return text;
    return text.replace(/\{(\w+)\}/g, function (match, name) {
      return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match;
    });
  }

  function t(key, params) {
    var value = boot.messages ? boot.messages[key] : null;
    if (typeof value !== "string") return key;
    return format(value, params);
  }

  /** True when the interface language is an unreviewed AGRIQ draft. */
  function isDraftLanguage() {
    return boot.status === "TRANSLATION_PENDING_REVIEW";
  }

  global.AgriqI18n = {
    lang: boot.lang || "en",
    status: boot.status || "source_language",
    t: t,
    isDraftLanguage: isDraftLanguage,
    missing: function () {
      return Object.keys(boot.messages || {}).length === 0;
    },
  };
})(window);
