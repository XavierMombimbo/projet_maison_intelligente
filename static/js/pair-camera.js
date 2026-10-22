(() => {
  "use strict";

  const data = document.getElementById("camera-credentials");
  const status = document.getElementById("credential-status");
  if (!data || !status) return;

  const paired = JSON.parse(data.textContent);
  window.SentinelleBrowserCameraStore.save({cameraId: paired.cameraId, pairedAt: Date.now(), pairingVersion: paired.pairingVersion})
    .then(() => {status.textContent = "Appairage enregistré pour les comptes autorisés. La webcam reste éteinte.";})
    .catch(() => {status.textContent = "Le navigateur n’a pas pu enregistrer l’appairage."; status.classList.add("error");});
})();
