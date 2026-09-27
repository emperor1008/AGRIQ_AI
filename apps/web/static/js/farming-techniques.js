/**
 * AGRIQ AI — Farming Techniques page behaviour (Phase 7.2).
 *
 * Progressive enhancement only: with JavaScript disabled every filter, search
 * and pagination control still works because the server renders the results.
 * With JavaScript enabled this module:
 *
 *   1. submits the language switcher on change (the GET form itself is the
 *      fallback, so the feature is keyboard- and screen-reader-friendly);
 *   2. auto-submits filter selects and debounces the search box;
 *   3. refreshes the results region from the JSON API, replacing it with the
 *      SAME server-rendered markup (never client-composed knowledge cards);
 *   4. keeps the address bar in sync so a filtered view is shareable.
 *
 * The client never invents agricultural content: it renders what the API
 * returns, including the canonical DATA_UNAVAILABLE / INSUFFICIENT_REAL_DATA
 * states, which arrive as text.
 */
(function (global) {
  "use strict";

  var DEBOUNCE_MS = 400;
  var t = function (key, params) {
    return global.AgriqI18n ? global.AgriqI18n.t(key, params) : key;
  };

  function selectLanguageSwitchers() {
    var selects = document.querySelectorAll("[data-language-select]");
    Array.prototype.forEach.call(selects, function (select) {
      select.addEventListener("change", function () {
        var form = select.form;
        if (form) form.submit();
      });
    });
  }

  function resultsUrl(form) {
    var params = new URLSearchParams(new FormData(form));
    var query = params.toString();
    return "/farming-techniques/partials/results" + (query ? "?" + query : "");
  }

  function shareableUrl(form) {
    var params = new URLSearchParams(new FormData(form));
    var query = params.toString();
    return "/farming-techniques" + (query ? "?" + query : "");
  }

  function setStatus(text) {
    var region = document.getElementById("knowledgeResults");
    if (!region || !text) return;
    region.setAttribute("aria-busy", "true");
    var banner = region.querySelector("[data-loading-banner]");
    if (!banner) {
      banner = document.createElement("p");
      banner.className = "knowledge-note";
      banner.setAttribute("data-loading-banner", "");
      banner.setAttribute("role", "status");
      region.insertBefore(banner, region.firstChild);
    }
    banner.textContent = text;
  }

  function clearStatus() {
    var region = document.getElementById("knowledgeResults");
    if (!region) return;
    region.removeAttribute("aria-busy");
    var banner = region.querySelector("[data-loading-banner]");
    if (banner) banner.remove();
  }

  function refresh(form) {
    var region = document.getElementById("knowledgeResults");
    if (!region || !global.fetch) return Promise.resolve();
    setStatus(t("js.searching"));
    return global
      .fetch(resultsUrl(form), { headers: { "X-Requested-With": "fetch" } })
      .then(function (response) {
        if (response.status === 401) {
          // Session ended: the server is the authority on that.
          global.location.assign("/login");
          return null;
        }
        if (!response.ok) throw new Error("knowledge_refresh_failed");
        return response.text();
      })
      .then(function (html) {
        if (html === null || html === undefined) return;
        region.innerHTML = html;
        clearStatus();
        syncAddressBar(form);
      })
      .catch(function () {
        // A failed refresh must leave the server-rendered results in place.
        clearStatus();
        var banner = document.createElement("p");
        banner.className = "knowledge-warning";
        banner.setAttribute("role", "alert");
        banner.textContent = t("js.error_loading");
        region.insertBefore(banner, region.firstChild);
      });
  }

  function syncAddressBar(form) {
    if (!global.history || !global.history.replaceState) return;
    try {
      global.history.replaceState({}, "", shareableUrl(form));
    } catch (error) {
      /* ignore: a non-shareable URL is a cosmetic problem, never a broken page */
    }
  }

  function wireFilters() {
    var form = document.querySelector("#knowledgeSearch form");
    if (!form) return;
    var search = form.querySelector('input[type="search"]');
    var timer = null;
    var submit = function () {
      refresh(form);
    };

    Array.prototype.forEach.call(form.querySelectorAll("select"), function (select) {
      select.addEventListener("change", submit);
    });
    if (search) {
      search.addEventListener("input", function () {
        if (timer) global.clearTimeout(timer);
        timer = global.setTimeout(submit, DEBOUNCE_MS);
      });
    }
    form.addEventListener("submit", function (event) {
      // Enter in the search box: refresh in place, keep a normal navigation as
      // the fallback when scripting fails later in the page's life.
      event.preventDefault();
      submit();
    });
  }

  function wireCategoryLinks() {
    var links = document.querySelectorAll("#knowledgeCategories a");
    Array.prototype.forEach.call(links, function (link) {
      link.addEventListener("click", function (event) {
        var form = document.querySelector("#knowledgeSearch form");
        if (!form) return; // no form: let the browser navigate normally
        event.preventDefault();
        var select = form.querySelector('select[name="category"]');
        if (select) select.value = link.getAttribute("data-category") || "";
        var search = form.querySelector('input[type="search"]');
        if (search) search.value = "";
        refresh(form);
      });
    });
  }

  function init() {
    selectLanguageSwitchers();
    wireFilters();
    wireCategoryLinks();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.AgriqFarmingTechniques = { init: init, refresh: refresh };
})(window);
