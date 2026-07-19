// Double-click-to-edit for a name (file display name, project name) — the
// one deliberate exception to this app's "no custom JS" rule besides the
// bulk-select-all checkbox toggle, since there's no CSS-only way to detect
// a double-click and swap to an editable field in place.
//
// Markup contract (see file_detail.html / project_detail.html):
//   <h1 class="editable-name">
//     <span class="editable-name-text">Current Name</span>
//     <form class="editable-name-form" method="POST" action="..." hidden>
//       <input type="text" name="...">
//     </form>
//   </h1>
//
// Event delegation on `document` — works for any number of instances on a
// page with no per-element setup.

function showEditForm(wrapper) {
  const textEl = wrapper.querySelector(".editable-name-text");
  const form = wrapper.querySelector(".editable-name-form");
  const input = form.querySelector("input");
  input.value = textEl.textContent.trim();
  textEl.hidden = true;
  form.hidden = false;
  input.focus();
  input.select();
}

function cancelEditForm(wrapper) {
  wrapper.querySelector(".editable-name-form").hidden = true;
  wrapper.querySelector(".editable-name-text").hidden = false;
}

document.addEventListener("dblclick", (event) => {
  const textEl = event.target.closest(".editable-name-text");
  if (!textEl) return;
  showEditForm(textEl.closest(".editable-name"));
});

document.addEventListener("keydown", (event) => {
  if (!event.target.matches(".editable-name-form input")) return;
  if (event.key === "Escape") {
    cancelEditForm(event.target.closest(".editable-name"));
  }
});

// Clicking/tabbing away without pressing Enter cancels rather than saves —
// an inline edit box that silently submits on blur risks an unintended
// save from a stray click elsewhere on the page.
document.addEventListener(
  "focusout",
  (event) => {
    if (!event.target.matches(".editable-name-form input")) return;
    cancelEditForm(event.target.closest(".editable-name"));
  },
  true
);

// Pressing Enter with the value unchanged from what was already displayed
// just reverts to display mode instead of submitting — avoids a no-op
// round trip, and (for file display names specifically) avoids turning an
// unset display_name's dynamic filename fallback into a frozen, explicit
// value just because the box was opened and closed.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.matches(".editable-name-form")) return;
  const wrapper = form.closest(".editable-name");
  const textEl = wrapper.querySelector(".editable-name-text");
  const input = form.querySelector("input");
  if (input.value.trim() === textEl.textContent.trim()) {
    event.preventDefault();
    cancelEditForm(wrapper);
  }
});
