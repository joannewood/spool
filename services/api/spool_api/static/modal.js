// Generic <dialog> wiring, shared by every modal on the file detail page
// (printed status, add tag, add to project) instead of each one carrying
// its own near-identical open/cancel/backdrop-click script. One of this
// app's few deliberate exceptions to "no custom JS" — native <dialog>
// needs a script to open it and to close on backdrop click (Escape-to-
// close is already built in).
//
// Markup contract:
//   <button class="modal-trigger" data-modal="some-modal-id">...</button>
//   <dialog id="some-modal-id" class="modal">
//     ...
//     <button type="button" class="modal-cancel">Cancel</button>
//   </dialog>
//
// Event delegation on `document` — works for any number of modals on a
// page with no per-modal setup.

document.addEventListener("click", (event) => {
  const trigger = event.target.closest(".modal-trigger");
  if (trigger) {
    document.getElementById(trigger.dataset.modal)?.showModal();
    return;
  }

  if (event.target.matches(".modal-cancel")) {
    event.target.closest("dialog")?.close();
    return;
  }

  // A click landing on the <dialog> element itself (not a descendant) is
  // a backdrop click, since the dialog's own box IS the content area —
  // anything inside it is a descendant, not the dialog element.
  if (event.target.matches("dialog") && event.target.open) {
    event.target.close();
  }
});
