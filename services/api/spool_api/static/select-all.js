// Bulk "select all" checkbox — toggles a set of otherwise-unrelated row
// checkboxes on an admin bulk-review page (duplicates, suggested projects,
// suggested relationships). No CSS-only technique makes one checkbox drive
// a set of others, so this is one of this app's few deliberate exceptions
// to "no custom JS." Previously each admin page carried its own copy of
// this same handful of lines with a different hardcoded id/class; unified
// into one generic, data-attribute-driven script instead.
//
// Markup contract:
//   <input type="checkbox" class="select-all-checkbox" data-target=".row-checkbox">
//   ...
//   <input type="checkbox" class="row-checkbox" ...>
//
// Event delegation on `document` — works for any number of instances on a
// page, or across different pages, with no per-page wiring.

document.addEventListener("change", (event) => {
  if (!event.target.matches(".select-all-checkbox")) return;
  document.querySelectorAll(event.target.dataset.target).forEach((cb) => {
    cb.checked = event.target.checked;
  });
});
