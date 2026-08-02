// Periodically re-fetches the status-aware favicon (see /favicon.svg in
// main.py, which colors the icon amber if the rescan loop looks stopped)
// so an already-open tab notices a status change without needing a
// reload -- browsers don't re-request a favicon on their own once
// loaded, so a fresh ?v= query param each tick is what forces one. The
// fourth deliberate exception to this app's "no custom JS" convention
// (alongside inline-edit.js/select-all.js/modal.js), for the same
// reason as the others: no CSS-only way to do this. A slow one-minute
// interval is plenty -- "the worker looks stopped" is a slow-moving
// state, not something that needs sub-minute precision.
setInterval(() => {
  const link = document.querySelector('link[rel="icon"]');
  if (link) link.href = "/favicon.svg?v=" + Date.now();
}, 60000);
