// Small vanilla JS for Subah (docs/03_TECH.md §1). Page-specific scripts are added per task.
(function () {
  function icons() {
    if (window.lucide) window.lucide.createIcons();
  }
  document.addEventListener("DOMContentLoaded", icons);
  document.body && document.body.addEventListener("htmx:afterSwap", icons);
  document.addEventListener("htmx:afterSwap", icons);
})();
