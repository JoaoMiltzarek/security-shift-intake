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

// Cockpit evidence overlay: click a field row -> highlight its probable region on the
// page image. Field data arrives as HTML-safe JSON in data-* attrs; we JSON.parse it and
// write only via textContent (never innerHTML), so OCR/human text can never inject markup.
function safeParse(raw) {
  try {
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

document.addEventListener("click", function (event) {
  const row = event.target.closest("tr[data-field]");
  if (!row) return;

  document
    .querySelectorAll("tr[data-field].active")
    .forEach((r) => r.classList.remove("active"));
  row.classList.add("active");

  const bbox = safeParse(row.dataset.bbox);
  const method = safeParse(row.dataset.method);
  const evidence = safeParse(row.dataset.evidence);
  const hl = document.getElementById("bbox-highlight");
  const note = document.getElementById("evidence-note");

  if (bbox && hl) {
    const [x0, y0, x1, y1] = bbox;
    hl.style.left = x0 * 100 + "%";
    hl.style.top = y0 * 100 + "%";
    hl.style.width = (x1 - x0) * 100 + "%";
    hl.style.height = (y1 - y0) * 100 + "%";
    hl.hidden = false;
    if (note) note.textContent = "Região provável destacada (método: " + (method || "?") + ").";
    return;
  }

  if (hl) hl.hidden = true;
  if (note) {
    if (method === "human_edit") {
      note.textContent = "Revisado manualmente — evidência de OCR anterior descartada.";
    } else {
      note.textContent =
        "Sem região visual encontrada. Evidência textual: «" +
        (evidence || "—") +
        "». Método: " + (method || "none") + ".";
    }
  }
});
