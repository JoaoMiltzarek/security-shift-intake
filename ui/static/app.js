"use strict";

function safeParse(raw) {
  try {
    return JSON.parse(raw);
  } catch (_error) {
    return null;
  }
}

function showNotice(message, options) {
  const notice = document.getElementById("app-notice");
  const text = document.getElementById("app-notice-message");
  const reload = document.getElementById("app-notice-reload");
  if (!notice || !text || !reload) return;

  text.textContent = message;
  reload.hidden = !(options && options.reload);
  notice.hidden = false;
  notice.focus({ preventScroll: true });
}

function reviewedBBox(raw) {
  const bbox = safeParse(raw);
  if (!Array.isArray(bbox) || bbox.length !== 4) return null;
  const values = bbox.map(Number);
  if (!values.every(Number.isFinite)) return null;
  const [x0, y0, x1, y1] = values;
  if (x0 < 0 || y0 < 0 || x1 > 1 || y1 > 1 || x0 >= x1 || y0 >= y1) return null;
  return values;
}

function clearEvidenceSelection() {
  document.querySelectorAll(".field-card.is-active").forEach(function (card) {
    card.classList.remove("is-active");
  });
  document.querySelectorAll(".evidence-trigger[aria-pressed='true']").forEach(function (button) {
    button.setAttribute("aria-pressed", "false");
  });
}

document.addEventListener("click", async function (event) {
  if (!(event.target instanceof Element)) return;
  const copyButton = event.target.closest("[data-copy-target]");
  if (copyButton) {
    const target = document.getElementById(copyButton.dataset.copyTarget);
    if (!target) return;
    try {
      await navigator.clipboard.writeText(target.innerText);
      showNotice("Mensagem copiada para a área de transferência.");
    } catch (_error) {
      showNotice("Não foi possível copiar automaticamente. Selecione o texto manualmente.");
    }
    return;
  }

  const clearButton = event.target.closest("[data-clear-row]");
  if (clearButton) {
    const occurrence = clearButton.closest(".occurrence-card");
    if (!occurrence) return;
    occurrence.querySelectorAll("input, select, textarea").forEach(function (control) {
      if (control instanceof HTMLInputElement && control.type === "radio") {
        control.checked = false;
      } else {
        control.value = "";
      }
    });
    occurrence.querySelector("input")?.focus();
    return;
  }

  const evidenceButton = event.target.closest(".evidence-trigger[data-field]");
  if (!evidenceButton) return;

  clearEvidenceSelection();
  evidenceButton.setAttribute("aria-pressed", "true");
  const card = document.getElementById(evidenceButton.dataset.card || "");
  card?.classList.add("is-active");

  const bbox = reviewedBBox(evidenceButton.dataset.bbox);
  const method = safeParse(evidenceButton.dataset.method);
  const evidence = safeParse(evidenceButton.dataset.evidence);
  const highlight = document.getElementById("bbox-highlight");
  const note = document.getElementById("evidence-note");

  if (bbox && highlight) {
    const [x0, y0, x1, y1] = bbox;
    highlight.setAttribute("x", String(x0 * 1000));
    highlight.setAttribute("y", String(y0 * 1000));
    highlight.setAttribute("width", String((x1 - x0) * 1000));
    highlight.setAttribute("height", String((y1 - y0) * 1000));
    highlight.removeAttribute("hidden");
    if (note) {
      note.textContent =
        "Região provável destacada. Método de localização: " + (method || "não informado") + ".";
    }
    return;
  }

  if (highlight) highlight.setAttribute("hidden", "");
  if (note) {
    note.textContent = evidence
      ? "Sem região visual. Evidência textual: “" + evidence + "”."
      : "Este campo não possui região visual ou evidência textual localizada.";
  }
});

document.getElementById("app-notice-reload")?.addEventListener("click", function () {
  window.location.reload();
});

document.body.addEventListener("htmx:beforeRequest", function (event) {
  const source = event.detail.elt;
  const container = source instanceof HTMLFormElement ? source : source.closest("form");
  container?.setAttribute("aria-busy", "true");
});

document.body.addEventListener("htmx:afterRequest", function (event) {
  const source = event.detail.elt;
  const container = source instanceof HTMLFormElement ? source : source.closest("form");
  container?.removeAttribute("aria-busy");

  if (event.detail.successful) return;
  const status = event.detail.xhr.status;
  if (status === 409) {
    showNotice("O documento mudou ou a ação conflita com o estado atual.", { reload: true });
  } else if (status === 422) {
    showNotice("Há valores inválidos. Revise os campos destacados e tente novamente.");
  } else {
    showNotice("A ação não foi concluída. O conteúdo digitado foi preservado.");
  }
});

document.body.addEventListener("htmx:afterSwap", function () {
  const error = document.getElementById("edit-error");
  if (error) error.focus({ preventScroll: false });
});
