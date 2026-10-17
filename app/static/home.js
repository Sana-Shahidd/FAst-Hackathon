// Edition page: filters (search, section pills, source circles), article sheet, dialogs (docs/07_DESIGN.md 3.1-3.2).
(function () {
  var query = "", section = "", source = "";
  var sheetOpenedAt = 0, sheetArticle = "";

  function matchesSource(cardSource) {
    if (!source) return true;
    return !!cardSource && (cardSource.indexOf(source) !== -1 || source.indexOf(cardSource) !== -1);
  }

  function applyFilters() {
    var shown = 0;
    document.querySelectorAll(".story").forEach(function (card) {
      var host = card.closest(".sec");
      var ok = (!query || card.textContent.toLowerCase().indexOf(query) !== -1)
        && (!section || (host && host.dataset.section === section))
        && matchesSource(card.dataset.source || "");
      card.hidden = !ok;
      if (ok) shown += 1;
    });
    document.querySelectorAll(".sec").forEach(function (sec) {
      sec.hidden = !sec.querySelector(".story:not([hidden])");
    });
    var none = document.getElementById("no-results");
    if (none) none.hidden = shown !== 0;
  }

  function pressOne(selector, activeEl) {
    document.querySelectorAll(selector).forEach(function (el) {
      var on = el === activeEl;
      el.setAttribute("aria-pressed", on ? "true" : "false");
      el.classList.toggle("is-active", on);
    });
  }

  // "Listen": the browser's own speech synthesis reads the story aloud, no server cost
  function stopListening() {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    document.querySelectorAll("[data-listen]").forEach(function (b) {
      b.setAttribute("aria-pressed", "false");
      b.closest("[data-listen-card]").classList.remove("is-playing");
    });
  }

  function toggleListen(button) {
    if (!window.speechSynthesis) return;
    var playing = button.getAttribute("aria-pressed") === "true";
    stopListening();
    if (playing) return;
    var utterance = new SpeechSynthesisUtterance(button.dataset.text);
    utterance.lang = button.dataset.lang || "en-US";
    utterance.onend = stopListening;
    button.setAttribute("aria-pressed", "true");
    button.closest("[data-listen-card]").classList.add("is-playing");
    window.speechSynthesis.speak(utterance);
  }

  function hideListenWithoutSpeech() {
    if (window.speechSynthesis) return;
    document.querySelectorAll("[data-listen-card]").forEach(function (c) { c.hidden = true; });
  }

  function closeSheet() {
    stopListening();
    var host = document.getElementById("sheet");
    if (!host || !host.firstElementChild) return;
    if (sheetArticle && sheetOpenedAt) {
      var data = new FormData();
      data.append("edition_article_id", sheetArticle);
      data.append("kind", "dwell");
      data.append("value", String(Math.round((Date.now() - sheetOpenedAt) / 1000)));
      try {
        var headers = JSON.parse(document.body.getAttribute("hx-headers") || "{}");
        data.append("csrf_token", headers["X-CSRF-Token"] || "");
        navigator.sendBeacon("/signals", data);
      } catch (e) { /* the dwell signal is optional */ }
    }
    sheetArticle = ""; sheetOpenedAt = 0;
    host.innerHTML = "";
    document.body.style.overflow = "";
  }

  // header video: honour "reduce motion" (CSS hides it, this also stops it from playing/downloading)
  var heroVideo = document.querySelector(".hero-video");
  if (heroVideo && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    heroVideo.removeAttribute("autoplay");
    heroVideo.pause();
    heroVideo.remove();
  }

  document.addEventListener("click", function (event) {
    var el = event.target.closest("button, a, summary, [data-close-sheet]");
    if (!el) return;
    if (el.id === "search-toggle") {
      var box = document.getElementById("search-box");
      box.hidden = !box.hidden;
      el.setAttribute("aria-expanded", String(!box.hidden));
      if (!box.hidden) document.getElementById("search-input").focus();
    } else if (el.hasAttribute("data-section-filter")) {
      section = el.dataset.sectionFilter;
      pressOne("[data-section-filter]", el);
      applyFilters();
    } else if (el.hasAttribute("data-source-filter")) {
      var turnOff = el.getAttribute("aria-pressed") === "true";
      source = turnOff ? "" : el.dataset.sourceFilter;
      pressOne("[data-source-filter]", turnOff ? null : el);
      applyFilters();
    } else if (el.hasAttribute("data-open-dialog")) {
      document.getElementById(el.dataset.openDialog).showModal();
    } else if (el.hasAttribute("data-close-dialog")) {
      el.closest("dialog").close();
    } else if (el.hasAttribute("data-close-sheet")) {
      closeSheet();
    } else if (el.hasAttribute("data-listen")) {
      toggleListen(el);
    } else if (el.hasAttribute("data-busy")) {
      // the first PDF of a day is rendered on demand; show it is working, then re-enable the link
      el.classList.add("is-loading");
      setTimeout(function () { el.classList.remove("is-loading"); }, 25000);
    } else if (el.hasAttribute("data-copy")) {
      var url = new URL(el.dataset.copy, window.location.origin).href;
      if (navigator.clipboard) navigator.clipboard.writeText(url);
    }
  });

  document.addEventListener("input", function (event) {
    if (event.target.id === "search-input") {
      query = event.target.value.trim().toLowerCase();
      applyFilters();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeSheet();
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail.target;
    if (target.id === "sheet" && target.firstElementChild) {
      var sheet = target.querySelector(".sheet");
      if (sheet && !sheetOpenedAt) {
        sheetOpenedAt = Date.now();
        sheetArticle = sheet.dataset.article;
      }
      document.body.style.overflow = "hidden";
      var close = target.querySelector(".round-btn[data-close-sheet]");
      if (close) close.focus();
    }
    hideListenWithoutSpeech();
    applyFilters();
  });
})();
