// Onboarding (F-02): five steps in one form. State lives in the form fields, so nothing is lost
// between steps; the final POST /onboarding sends everything at once.
(function () {
  const form = document.getElementById("ob-form");
  if (!form) return;

  const total = Number(form.dataset.steps);
  const steps = [...form.querySelectorAll(".ob-step")];
  const dots = [...form.querySelectorAll(".dot")];
  const next = document.getElementById("ob-next");
  const back = document.getElementById("ob-back");
  const kicker = document.getElementById("ob-kicker");
  const alertBox = document.getElementById("ob-alert");
  const field = (id) => document.getElementById(id);
  let step = 1;

  function icons() {
    if (window.lucide) window.lucide.createIcons();
  }

  function warn(message) {
    alertBox.textContent = message || "";
    alertBox.hidden = !message;
  }

  function selectedTopics() {
    return [...form.querySelectorAll('input[name="topics"]:checked')].map((i) => i.value);
  }

  function show(n) {
    step = n;
    steps.forEach((s, i) => (s.hidden = i + 1 !== n));
    dots.forEach((d, i) => d.classList.toggle("is-active", i + 1 === n));
    kicker.textContent = form.dataset.stepLabel.replace("__N__", n);
    next.textContent = n === total ? form.dataset.finish : form.dataset.next;
    warn("");
    window.scrollTo(0, 0);
    if (n === 4) loadTaste();
    icons();
  }

  next.addEventListener("click", () => {
    if (step === 2 && selectedTopics().length < 3) {
      warn(form.dataset.minMsg);
      return;
    }
    if (step === total) form.requestSubmit ? form.requestSubmit() : form.submit();
    else show(step + 1);
  });
  back.addEventListener("click", () => (step > 1 ? show(step - 1) : (location.href = "/")));
  form.addEventListener("submit", (e) => {
    if (selectedTopics().length < 3) {
      e.preventDefault();
      show(2);
      warn(form.dataset.minMsg);
    }
  });
  // Enter inside a text field adds its chip instead of submitting the whole form.
  form.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.target.tagName !== "INPUT") return;
    e.preventDefault();
    if (e.target.id === "custom-text") field("parse-btn").click();
    if (e.target.id === "feed-url") form.querySelector('[hx-post="/onboarding/feed"]').click();
    if (e.target.id === "mute-input") field("mute-add").click();
  });

  // Step 1: choosing the language re-renders the page in it (and mirrors RTL).
  form.querySelectorAll("[data-switch-lang]").forEach((radio) =>
    radio.addEventListener("change", () => (location.href = "/onboarding?lang=" + radio.value))
  );

  // Step 2: topic cards, "how much" levels, favourite outlets.
  const count = field("topic-count");
  form.querySelectorAll(".topic-card").forEach((card) => {
    const box = card.querySelector('input[type="checkbox"]');
    const sync = () => {
      card.classList.toggle("is-selected", box.checked);
      count.textContent = selectedTopics().length;
      warn("");
    };
    box.addEventListener("change", sync);
    card.querySelectorAll(".level-btn").forEach((btn) =>
      btn.addEventListener("click", () => {
        card.querySelector('input[type="hidden"]').value = btn.dataset.level;
        card.querySelectorAll(".level-btn").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      })
    );
  });
  const writeFavorites = () => {
    const keys = [...form.querySelectorAll(".source-dot[aria-pressed='true']")].map((b) => b.dataset.key);
    field("favorite_sources").value = JSON.stringify(keys.slice(0, 10));
  };
  form.querySelectorAll(".source-dot").forEach((dot) =>
    dot.addEventListener("click", () => {
      dot.setAttribute("aria-pressed", String(dot.getAttribute("aria-pressed") !== "true"));
      writeFavorites();
    })
  );

  // Chip lists filled by HTMX (interests, pasted feeds) or locally (muted words).
  function writeChips(listId, inputId, read) {
    const list = field(listId);
    field(inputId).value = JSON.stringify([...list.querySelectorAll(".chip")].map(read));
  }
  const readInterest = (li) => ({ label: li.dataset.label, query: li.dataset.query });
  const readFeed = (li) => li.dataset.url;
  const readMute = (li) => li.dataset.word;
  const lists = [
    ["interest-chips", "custom_interests", readInterest],
    ["feed-chips", "custom_feeds", readFeed],
    ["mute-chips", "muted_keywords", readMute],
  ];
  lists.forEach(([listId, inputId, read]) => {
    const list = field(listId);
    list.addEventListener("click", (e) => {
      const x = e.target.closest(".chip-x");
      if (x) {
        x.closest(".chip").remove();
        writeChips(listId, inputId, read);
      }
    });
    document.body.addEventListener("htmx:afterSwap", (e) => {
      if (e.detail.target === list) {
        const chips = list.querySelectorAll(".chip");
        if (listId === "feed-chips") [...chips].slice(5).forEach((c) => c.remove());
        writeChips(listId, inputId, read);
        icons();
      }
    });
  });

  // Step 5: muted words.
  const muteInput = field("mute-input");
  field("mute-add").addEventListener("click", () => {
    const word = muteInput.value.trim().toLowerCase();
    const list = field("mute-chips");
    const have = [...list.querySelectorAll(".chip")].map((c) => c.dataset.word);
    if (word.length >= 2 && word.length <= 40 && have.length < 30 && !have.includes(word)) {
      const li = document.createElement("li");
      li.className = "chip";
      li.dataset.word = word;
      const label = document.createElement("span");
      label.textContent = word;
      const x = document.createElement("button");
      x.type = "button";
      x.className = "chip-x";
      x.setAttribute("aria-label", "×");
      x.textContent = "×";
      li.append(label, x);
      list.append(li);
      writeChips("mute-chips", "muted_keywords", readMute);
    }
    muteInput.value = "";
  });
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (zone) field("timezone").value = zone;

  // Step 4: taste test with real headlines (buttons, or swipe right/left).
  const votes = [];
  let tasteTopics = "";
  function loadTaste() {
    const topics = selectedTopics().join(",");
    if (topics === tasteTopics) return;
    tasteTopics = topics;
    votes.length = 0;
    field("taste_votes").value = "[]";
    htmx.ajax("GET", "/onboarding/taste?topics=" + encodeURIComponent(topics), {
      target: "#taste",
      swap: "innerHTML",
    }).then(() => {
      showCard();
      icons();
    });
  }
  function cards() {
    return [...document.querySelectorAll("#taste .taste-card")];
  }
  function showCard() {
    const all = cards();
    const current = all[votes.length];
    all.forEach((c, i) => (c.hidden = i !== votes.length));
    field("taste-progress").textContent = all.length ? Math.min(votes.length + 1, all.length) + " / " + all.length : "";
    if (!current) field("taste-progress").textContent = "";
  }
  function vote(kind) {
    const current = cards()[votes.length];
    if (!current) return;
    votes.push({ topic_key: current.dataset.topic, vote: kind });
    field("taste_votes").value = JSON.stringify(votes.filter((v) => v.vote !== "skip"));
    if (votes.length >= cards().length) {
      show(5);
    } else {
      showCard();
    }
  }
  field("taste").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-vote]");
    if (btn) vote(btn.dataset.vote);
  });
  let startX = null;
  field("taste").addEventListener("pointerdown", (e) => (startX = e.clientX));
  field("taste").addEventListener("pointerup", (e) => {
    if (startX === null) return;
    const dx = e.clientX - startX;
    startX = null;
    if (Math.abs(dx) > 90) vote(dx > 0 ? "up" : "down");
  });

  icons();
})();
