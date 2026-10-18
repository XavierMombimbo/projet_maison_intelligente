(() => {
  "use strict";
  const current = document.body.dataset.cameraSessionContext || "";
  const key = "sentinelle-camera-session";
  const changed = value => {
    if (value !== current) window.dispatchEvent(new Event("sentinelle:account-changed"));
  };
  try {
    const channel = new BroadcastChannel(key);
    channel.onmessage = event => changed(event.data);
    channel.postMessage(current);
  } catch (_) { /* The server still checks the session on every request. */ }
  window.addEventListener("storage", event => { if (event.key === key) changed(event.newValue || ""); });
  try { localStorage.setItem(key, current); } catch (_) { /* Private browsing may disable storage. */ }
})();
