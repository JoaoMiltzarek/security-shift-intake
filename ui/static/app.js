// Small same-origin helpers (no inline handlers, CSP-friendly).
// Copy-to-clipboard via event delegation so it keeps working after HTMX swaps
// replace the review body.
document.addEventListener("click", function (event) {
  const btn = event.target.closest("[data-copy-target]");
  if (!btn) return;
  const target = document.getElementById(btn.dataset.copyTarget);
  if (target) {
    navigator.clipboard.writeText(target.innerText);
  }
});
