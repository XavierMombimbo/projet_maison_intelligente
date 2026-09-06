(() => {
  "use strict";

  const panel = document.getElementById("realtime-alerts") || document.getElementById("global-alert-runtime");
  if (!panel) return;

  const state = document.getElementById("ws-state");
  const indicator = document.getElementById("ws-indicator");
  const soundButton = document.getElementById("sound-toggle");
  const toasts = document.getElementById("alert-toasts");
  const alertList = document.getElementById("recent-alerts");
  const count = document.getElementById("new-alert-count");
  const confirmedCount = document.getElementById("confirmed-alert-count");
  const statusLabels = {
    new: "Nouveau",
    false_alarm: "Fausse alerte",
    confirmed: "Intrusion confirmée",
  };
  let socket;
  let retryTimer;
  let pingTimer;
  let retries = 0;
  let audioContext;
  let activeAlarmNodes = [];
  let soundEnabled = localStorage.getItem("sentinelle-alert-sound") === "on";

  function setConnection(label, className) {
    if (state) state.textContent = label;
    if (indicator) indicator.className = `connection-dot ${className}`;
  }

  function updateSoundButton() {
    if (!soundButton) return;
    soundButton.textContent = soundEnabled ? "Couper la sirène" : "Activer la sirène";
    soundButton.setAttribute("aria-pressed", String(soundEnabled));
  }

  function ensureAudioContext() {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return null;
    audioContext ||= new AudioContext();
    if (audioContext.state === "suspended") audioContext.resume();
    return audioContext;
  }

  function stopActiveAlarm() {
    activeAlarmNodes.forEach((node) => {
      try { node.stop(); } catch (_error) { /* déjà arrêtée */ }
      try { node.disconnect(); } catch (_error) { /* déjà déconnectée */ }
    });
    activeAlarmNodes = [];
  }

  function playAlarm() {
    if (!soundEnabled) return;
    const context = ensureAudioContext();
    if (!context) return;
    stopActiveAlarm();
    const start = context.currentTime + 0.02;
    const duration = 5;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sawtooth";
    oscillator.frequency.setValueAtTime(620, start);
    for (let offset = 0; offset < duration; offset += 0.42) {
      oscillator.frequency.linearRampToValueAtTime(980, start + offset + 0.21);
      oscillator.frequency.linearRampToValueAtTime(620, start + offset + 0.42);
    }
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.13, start + 0.06);
    gain.gain.setValueAtTime(0.13, start + duration - 0.15);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + duration + 0.02);
    activeAlarmNodes = [oscillator];
    oscillator.addEventListener("ended", () => {
      activeAlarmNodes = activeAlarmNodes.filter((node) => node !== oscillator);
    });
  }

  function safeDetailUrl(value) {
    return typeof value === "string" && value.startsWith("/") && !value.startsWith("//")
      ? value
      : "#";
  }

  function alertTitle(payload) {
    return payload.simulated ? "Simulation de détection" : "Personne détectée";
  }

  function showToast(payload) {
    const toast = document.createElement("aside");
    toast.className = "alert-toast";
    const title = document.createElement("strong");
    title.textContent = alertTitle(payload);
    const details = document.createElement("span");
    details.textContent = `${payload.camera_name} · ${payload.house_name} · confiance ${Math.round(Number(payload.confidence) * 100)} %`;
    const link = document.createElement("a");
    link.href = safeDetailUrl(payload.detail_url);
    link.textContent = "Vérifier l’alerte";
    const close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "Fermer l’alerte");
    close.textContent = "×";
    close.addEventListener("click", () => toast.remove());
    toast.append(title, details, link, close);
    toasts.prepend(toast);
    window.setTimeout(() => toast.remove(), 15000);
  }

  function createAlertRow(payload) {
    if (!alertList) return;
    document.getElementById("no-alerts")?.remove();
    document.getElementById(`alert-${payload.event_id}`)?.remove();
    const row = document.createElement("a");
    row.id = `alert-${payload.event_id}`;
    row.className = "event-row is-new";
    row.dataset.status = payload.status;
    row.href = safeDetailUrl(payload.detail_url);
    const title = document.createElement("strong");
    title.textContent = alertTitle(payload);
    const location = document.createElement("span");
    location.textContent = `${payload.camera_name} · ${payload.house_name}`;
    const eventStatus = document.createElement("span");
    eventStatus.className = `status-pill ${payload.status} event-status`;
    eventStatus.textContent = statusLabels[payload.status] || payload.status;
    const timestamp = document.createElement("time");
    const createdAt = new Date(payload.created_at);
    timestamp.dateTime = payload.created_at;
    timestamp.textContent = Number.isNaN(createdAt.getTime())
      ? "À l’instant"
      : createdAt.toLocaleString("fr-FR");
    row.append(title, location, eventStatus, timestamp);
    alertList.prepend(row);
    while (alertList.children.length > 8) alertList.lastElementChild.remove();
  }

  function handleMessage(payload) {
    if (payload.type === "alert.created") {
      showToast(payload);
      createAlertRow(payload);
      if (count) count.textContent = String(Number.parseInt(count.textContent || "0", 10) + 1);
      playAlarm();
    } else if (payload.type === "alert.updated") {
      const row = document.getElementById(`alert-${payload.event_id}`);
      const status = row?.querySelector(".event-status");
      if (status) {
        status.textContent = statusLabels[payload.status] || payload.status;
        status.classList.remove("new", "false_alarm", "confirmed");
        status.classList.add(payload.status);
      }
      if (count && row?.dataset.status === "new" && payload.status !== "new") {
        count.textContent = String(Math.max(0, Number.parseInt(count.textContent || "0", 10) - 1));
      }
      if (confirmedCount && row?.dataset.status !== "confirmed" && payload.status === "confirmed") {
        confirmedCount.textContent = String(Number.parseInt(confirmedCount.textContent || "0", 10) + 1);
      }
      if (row) row.dataset.status = payload.status;
    }
  }

  function connect() {
    window.clearTimeout(retryTimer);
    setConnection(retries ? "Reconnexion aux alertes…" : "Connexion aux alertes…", "is-connecting");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${window.location.host}${panel.dataset.wsPath}`);
    socket.addEventListener("open", () => {
      retries = 0;
      setConnection("Alertes en temps réel actives", "is-online");
      window.clearInterval(pingTimer);
      pingTimer = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
      }, 25000);
    });
    socket.addEventListener("message", (event) => {
      try { handleMessage(JSON.parse(event.data)); } catch (_error) { /* message ignoré */ }
    });
    socket.addEventListener("close", () => {
      window.clearInterval(pingTimer);
      retries += 1;
      const delay = Math.min(30000, 1000 * (2 ** Math.min(retries - 1, 5)));
      setConnection("Connexion perdue — nouvelle tentative…", "is-offline");
      retryTimer = window.setTimeout(connect, delay);
    });
    socket.addEventListener("error", () => socket.close());
  }

  if (soundButton) {
    soundButton.addEventListener("click", () => {
      soundEnabled = !soundEnabled;
      localStorage.setItem("sentinelle-alert-sound", soundEnabled ? "on" : "off");
      if (soundEnabled) ensureAudioContext();
      else stopActiveAlarm();
      updateSoundButton();
    });
  }
  updateSoundButton();
  connect();
})();
