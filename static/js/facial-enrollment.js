(() => {
  "use strict";
  const root = document.querySelector("[data-face-enrollment]");
  const form = root?.querySelector("[data-face-form]");
  if (!form) return;
  const video = root.querySelector("[data-face-video]");
  const preview = root.querySelector("[data-face-preview]");
  const consent = root.querySelector("[data-face-consent]");
  const start = root.querySelector("[data-face-start]");
  const save = root.querySelector("[data-face-save]");
  const cancel = root.querySelector("[data-face-cancel]");
  const status = root.querySelector("[data-face-status]");
  let stream = null;
  let generation = 0;
  let busy = false;
  const stop = () => {
    generation += 1;
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
    video.srcObject = null;
    preview.hidden = true;
    save.hidden = true;
    cancel.hidden = true;
    start.hidden = false;
  };
  start.addEventListener("click", async () => {
    if (busy) return;
    if (!consent.checked) {
      status.textContent = "Confirmez votre accord avant d’ouvrir la caméra.";
      consent.focus();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      status.textContent = "La caméra nécessite un navigateur compatible et une connexion HTTPS.";
      return;
    }
    const current = ++generation;
    start.disabled = true;
    status.textContent = "Autorisez l’accès à la caméra dans votre navigateur.";
    try {
      const opened = await navigator.mediaDevices.getUserMedia({audio: false, video: {facingMode: "user", width: {ideal: 640}, height: {ideal: 480}}});
      if (current !== generation || document.hidden) {
        opened.getTracks().forEach(track => track.stop());
        return;
      }
      stream = opened;
      video.srcObject = stream;
      preview.hidden = false;
      await video.play();
      start.hidden = true;
      save.hidden = false;
      cancel.hidden = false;
      status.textContent = "Gardez votre visage visible, puis cliquez sur Enregistrer mon visage.";
    } catch (error) {
      stop();
      status.textContent = error.name === "NotAllowedError"
        ? "Accès refusé. Autorisez la caméra dans votre navigateur pour réessayer."
        : "Caméra indisponible. Fermez les applications qui l’utilisent, puis réessayez.";
    } finally {
      start.disabled = false;
    }
  });
  cancel.addEventListener("click", () => { stop(); status.textContent = "Caméra fermée. Aucune capture n’a été envoyée."; });
  consent.addEventListener("change", () => { if (!consent.checked) stop(); });
  window.addEventListener("pagehide", stop);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || !consent.checked || !stream) return;
    if (!video.videoWidth || !video.videoHeight) { status.textContent = "Attendez que la caméra affiche votre visage."; return; }
    busy = true;
    start.disabled = true;
    save.disabled = true;
    consent.disabled = true;
    root.setAttribute("aria-busy", "true");
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    let image = "";
    let timeout;
    try {
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      image = canvas.toDataURL("image/jpeg", 0.8).split(",")[1];
      stop();
      status.textContent = "Enregistrement en cours…";
      const controller = new AbortController();
      timeout = setTimeout(() => controller.abort(), 90000);
      const response = await fetch(root.dataset.submitUrl, {
        method: "POST", credentials: "same-origin", mode: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value},
        body: JSON.stringify({image, consent: true}), signal: controller.signal,
      });
      const data = response.headers.get("Content-Type")?.includes("application/json") ? await response.json() : null;
      if (!response.ok || data?.status !== "enrolled") {
        status.textContent = data?.detail || "Session expirée ou enregistrement impossible. Rechargez la page pour réessayer.";
        return;
      }
      form.hidden = true;
      root.querySelector("[data-face-success]").hidden = false;
      root.querySelector("h1").textContent = "Votre visage est enregistré";
      status.textContent = "Votre profil est prêt pour les caméras de cette maison.";
    } catch (_) {
      stop();
      status.textContent = "La confirmation n’a pas pu être reçue. Revenez à vos profils pour vérifier l’état avant de réessayer.";
    } finally {
      clearTimeout(timeout);
      image = "";
      canvas.width = canvas.height = 0;
      busy = false;
      start.disabled = save.disabled = consent.disabled = false;
      root.removeAttribute("aria-busy");
    }
  });
})();
