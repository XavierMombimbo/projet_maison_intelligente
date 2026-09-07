(() => {
  "use strict";

  const DB_NAME = "sentinelle-camera";
  const STORE_NAME = "credentials";
  const PERSON_THRESHOLD = 0.45;
  const REQUIRED_STABLE_FRAMES = 1;
  const DETECTION_INTERVAL_MS = 350;
  const EVENT_COOLDOWN_MS = 15000;

  const openDatabase = () => new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME, {keyPath: "cameraId"});
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  const readCredentials = async () => {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const request = database.transaction(STORE_NAME).objectStore(STORE_NAME).getAll();
      request.onsuccess = () => {
        const values = request.result || [];
        values.sort((left, right) => (right.pairedAt || 0) - (left.pairedAt || 0));
        resolve(values[0] || null);
      };
      request.onerror = () => reject(request.error);
    });
  };

  const saveCredentials = async (credentials) => {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).put(credentials);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
    });
  };

  const deleteCredentials = async (cameraId) => {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).delete(cameraId);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
    });
  };

  const tokenExpiresSoon = (token) => {
    try {
      const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      const padded = encoded.padEnd(encoded.length + ((4 - encoded.length % 4) % 4), "=");
      const payload = JSON.parse(atob(padded));
      return !payload.exp || payload.exp * 1000 < Date.now() + 30000;
    } catch (_) {
      return true;
    }
  };

  const bytesToHex = (bytes) => Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");

  const signDetection = async ({credentials, path, timestamp, nonce, eventId, confidence, simulated, blob}) => {
    if (!credentials.eventSigningKey || !window.crypto?.subtle) {
      throw new Error("La signature cryptographique de la caméra est indisponible.");
    }
    const encoder = new TextEncoder();
    const captureDigest = bytesToHex(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())));
    const payload = [
      "sentinelle-event-v1",
      "POST",
      path,
      credentials.cameraId,
      String(timestamp),
      nonce,
      eventId,
      Number(confidence).toFixed(6),
      simulated ? "1" : "0",
      captureDigest
    ].join("\n");
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(credentials.eventSigningKey),
      {name: "HMAC", hash: "SHA-256"},
      false,
      ["sign"]
    );
    const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
    return bytesToHex(new Uint8Array(signature));
  };

  document.addEventListener("DOMContentLoaded", async () => {
    const root = document.getElementById("camera-monitor");
    if (!root) return;

    const video = document.getElementById("camera-video");
    const overlay = document.getElementById("detection-overlay");
    const context = overlay.getContext("2d");
    const startButton = document.getElementById("start-camera");
    const stopButton = document.getElementById("stop-camera");
    const simulationButton = document.getElementById("simulate-detection");
    const cameraStatus = document.getElementById("camera-status");
    const monitoringState = document.getElementById("monitoring-state");
    const modelState = document.getElementById("model-state");
    const stabilityState = document.getElementById("stability-state");
    const lastEvent = document.getElementById("last-event");
    const cameraOff = document.getElementById("camera-off");
    const liveIndicator = document.getElementById("live-indicator");
    const pairingLink = document.getElementById("pairing-link");
    const controlStatusDot = document.getElementById("control-status-dot");

    let credentials = null;
    let stream = null;
    let model = null;
    let running = false;
    let analysisBusy = false;
    let monitoringActive = false;
    let consecutiveFrames = 0;
    let cooldownUntil = 0;
    let detectionTimer = null;
    let stateTimer = null;
    let heartbeatTimer = null;
    let serverClockOffsetMs = 0;

    const synchronizeServerClock = (response, requestStartedAt) => {
      const serverTimestamp = Date.parse(response.headers.get("Date") || "");
      if (!Number.isFinite(serverTimestamp)) return;
      const requestFinishedAt = Date.now();
      const requestMidpoint = requestStartedAt + (requestFinishedAt - requestStartedAt) / 2;
      serverClockOffsetMs = serverTimestamp - requestMidpoint;
    };

    const loadRuntimeScript = (source) => new Promise((resolve, reject) => {
      const url = new URL(source, window.location.origin);
      url.searchParams.set("retry", String(Date.now()));
      const script = document.createElement("script");
      script.src = url.toString();
      script.onload = resolve;
      script.onerror = () => reject(new Error(`Chargement impossible : ${url.pathname}`));
      document.head.appendChild(script);
    });

    const visionRuntimeReady = () => (
      Boolean(window.tf)
      && typeof window.tf.loadGraphModel === "function"
      && Boolean(window.cocoSsd)
      && typeof window.cocoSsd.load === "function"
    );

    const yoloRuntimeReady = () => Boolean(window.YoloDetector) && Boolean(window.ort?.InferenceSession);

    const ensureVisionRuntime = async () => {
      if (visionRuntimeReady()) return;
      window.tf = {};
      window.cocoSsd = {};
      await loadRuntimeScript(root.dataset.tensorflowUrl);
      await loadRuntimeScript(root.dataset.cocoUrl);
      if (!visionRuntimeReady()) {
        throw new Error("Le moteur IA n’a pas pu être initialisé dans ce navigateur.");
      }
    };

    const setStatus = (message, isError = false) => {
      cameraStatus.textContent = message;
      cameraStatus.classList.toggle("error", isError);
      controlStatusDot?.classList.toggle("offline", isError);
      controlStatusDot?.classList.toggle("danger", isError);
    };

    const webcamErrorMessage = (error) => {
      if (!window.isSecureContext || error?.name === "InsecureContextError") {
        return "Webcam bloquée : cette adresse HTTP n’est pas considérée comme sécurisée. Utilisez HTTPS ou ouvrez Chrome avec l’origine locale autorisée.";
      }
      if (["NotAllowedError", "PermissionDeniedError", "SecurityError"].includes(error?.name)) {
        return "Permission webcam refusée. Cliquez sur l’icône caméra ou cadenas de la barre d’adresse, choisissez Autoriser, puis rechargez la page.";
      }
      if (["NotFoundError", "DevicesNotFoundError"].includes(error?.name)) {
        return "Aucune webcam détectée. Vérifiez sa connexion et son activation dans le système.";
      }
      if (["NotReadableError", "TrackStartError", "AbortError"].includes(error?.name)) {
        return "Webcam indisponible ou déjà utilisée. Fermez Zoom, Teams, Cheese et les autres applications utilisant la caméra, puis réessayez.";
      }
      return `Impossible de démarrer la webcam (${error?.name || "erreur inconnue"}). La simulation reste disponible.`;
    };

    const requestCameraStream = async () => {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        const error = new Error("Contexte navigateur non sécurisé");
        error.name = "InsecureContextError";
        throw error;
      }
      try {
        return await navigator.mediaDevices.getUserMedia({
          video: {width: {ideal: 1280}, height: {ideal: 720}, facingMode: {ideal: "environment"}},
          audio: false
        });
      } catch (error) {
        if (error?.name !== "OverconstrainedError") throw error;
        return navigator.mediaDevices.getUserMedia({video: true, audio: false});
      }
    };

    const renewToken = async () => {
      const requestStartedAt = Date.now();
      const response = await fetch(root.dataset.tokenUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({device_id: credentials.deviceId, device_secret: credentials.deviceSecret})
      });
      synchronizeServerClock(response, requestStartedAt);
      if (!response.ok) {
        const error = new Error(
          response.status === 401
            ? "Identité caméra expirée ou révoquée. Appairez de nouveau cet appareil."
            : "Le serveur n’a pas pu renouveler l’identité caméra."
        );
        error.code = response.status === 401 ? "INVALID_CREDENTIALS" : "TOKEN_RENEWAL_FAILED";
        throw error;
      }
      const body = await response.json();
      credentials.accessToken = body.access_token;
      credentials.eventSigningKey = body.event_signing_key;
      await saveCredentials(credentials);
      return credentials.accessToken;
    };

    const validToken = async () => {
      if (!credentials.accessToken || !credentials.eventSigningKey || tokenExpiresSoon(credentials.accessToken)) return renewToken();
      return credentials.accessToken;
    };

    const cameraFetch = async (url, options = {}, retry = true) => {
      const token = await validToken();
      const headers = new Headers(options.headers || {});
      headers.set("Authorization", `Bearer ${token}`);
      const requestStartedAt = Date.now();
      const response = await fetch(url, {...options, headers});
      synchronizeServerClock(response, requestStartedAt);
      if (response.status === 401 && retry) {
        await renewToken();
        return cameraFetch(url, options, false);
      }
      return response;
    };

    const refreshState = async () => {
      try {
        const response = await cameraFetch(root.dataset.stateUrl);
        if (!response.ok) throw new Error("La caméra ne peut plus lire son état.");
        const state = await response.json();
        monitoringActive = state.monitoring_active;
        document.getElementById("camera-title").textContent = state.name;
        monitoringState.textContent = monitoringActive ? "Surveillance activée" : "Surveillance désactivée";
        monitoringState.classList.toggle("active", monitoringActive);
        if (!monitoringActive) {
          consecutiveFrames = 0;
          stabilityState.textContent = `0 / ${REQUIRED_STABLE_FRAMES} image`;
        }
      } catch (error) {
        monitoringActive = false;
        if (error.code === "INVALID_CREDENTIALS" && credentials) {
          await deleteCredentials(credentials.cameraId).catch(() => {});
          credentials = null;
          pairingLink.hidden = false;
          simulationButton.disabled = true;
        }
        setStatus(error.message, true);
        stopCamera();
      }
    };

    const heartbeat = async () => {
      if (!credentials) return;
      try { await cameraFetch(root.dataset.heartbeatUrl, {method: "POST"}); } catch (_) { /* next state poll reports it */ }
    };

    const drawPredictions = (predictions) => {
      overlay.width = video.videoWidth || 640;
      overlay.height = video.videoHeight || 360;
      context.clearRect(0, 0, overlay.width, overlay.height);
      context.lineWidth = 4;
      context.font = "18px system-ui";
      predictions.filter(item => item.class === "person" && item.score >= PERSON_THRESHOLD).forEach(item => {
        const [x, y, width, height] = item.bbox;
        context.strokeStyle = "#26e39a";
        context.fillStyle = "#26e39a";
        context.strokeRect(x, y, width, height);
        context.fillText(`Personne ${Math.round(item.score * 100)}%`, x, Math.max(20, y - 8));
      });
    };

    const frameBlob = (simulated) => new Promise((resolve) => {
      const canvas = document.createElement("canvas");
      const sourceWidth = stream ? video.videoWidth : 640;
      const sourceHeight = stream ? video.videoHeight : 360;
      const scale = Math.min(1, 640 / Math.max(sourceWidth, 1));
      canvas.width = Math.max(1, Math.round(sourceWidth * scale));
      canvas.height = Math.max(1, Math.round(sourceHeight * scale));
      const frameContext = canvas.getContext("2d");
      if (stream) {
        frameContext.drawImage(video, 0, 0, canvas.width, canvas.height);
      } else {
        frameContext.fillStyle = "#16231f";
        frameContext.fillRect(0, 0, canvas.width, canvas.height);
      }
      if (simulated) {
        frameContext.fillStyle = "rgba(239, 201, 76, .92)";
        frameContext.fillRect(0, canvas.height - 68, canvas.width, 68);
        frameContext.fillStyle = "#292000";
        frameContext.font = "bold 22px system-ui";
        frameContext.fillText("SIMULATION DE DÉTECTION", 18, canvas.height - 36);
        frameContext.font = "14px system-ui";
        frameContext.fillText(new Date().toLocaleString(), 18, canvas.height - 14);
      }
      canvas.toBlob(resolve, "image/jpeg", .72);
    });

    const transmitEvent = async (confidence, simulated) => {
      if (!monitoringActive) {
        setStatus("Activez d’abord la surveillance depuis le compte propriétaire.", true);
        return;
      }
      const blob = await frameBlob(simulated);
      const eventId = crypto.randomUUID();
      const requestNonce = crypto.randomUUID();
      const requestTimestamp = Math.floor((Date.now() + serverClockOffsetMs) / 1000);
      const formData = new FormData();
      formData.append("event_id", eventId);
      formData.append("confidence", String(confidence));
      formData.append("simulated", simulated ? "true" : "false");
      formData.append("capture", blob, simulated ? "simulation.jpg" : "detection.jpg");
      try {
        await validToken();
        const signature = await signDetection({
          credentials,
          path: new URL(root.dataset.detectionUrl, window.location.origin).pathname,
          timestamp: requestTimestamp,
          nonce: requestNonce,
          eventId,
          confidence,
          simulated,
          blob
        });
        const response = await cameraFetch(root.dataset.detectionUrl, {
          method: "POST",
          headers: {
            "X-Camera-Timestamp": String(requestTimestamp),
            "X-Camera-Nonce": requestNonce,
            "X-Camera-Signature": signature
          },
          body: formData
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Échec de la transmission.");
        cooldownUntil = Date.now() + EVENT_COOLDOWN_MS;
        lastEvent.textContent = `${simulated ? "Simulation" : "Détection"} envoyée à ${new Date().toLocaleTimeString()}`;
        setStatus("Événement transmis ; le flux vidéo reste local.");
      } catch (error) {
        setStatus(error.message, true);
      }
    };

    const analyzeFrame = async () => {
      if (!running || !monitoringActive || !model || analysisBusy || video.readyState < 2) return;
      analysisBusy = true;
      try {
        const predictions = await model.detect(video);
        drawPredictions(predictions);
        const persons = predictions.filter(item => item.class === "person" && item.score >= PERSON_THRESHOLD);
        consecutiveFrames = persons.length ? consecutiveFrames + 1 : 0;
        stabilityState.textContent = `${Math.min(consecutiveFrames, REQUIRED_STABLE_FRAMES)} / ${REQUIRED_STABLE_FRAMES} images`;
        if (consecutiveFrames >= REQUIRED_STABLE_FRAMES && Date.now() >= cooldownUntil) {
          const confidence = Math.max(...persons.map(item => item.score));
          consecutiveFrames = 0;
          await transmitEvent(confidence, false);
        }
      } catch (error) {
        modelState.textContent = "Erreur du modèle — simulation disponible";
        setStatus("L’analyse IA a échoué, mais la webcam peut rester en aperçu.", true);
      } finally {
        analysisBusy = false;
      }
    };

    const scheduleAnalysis = (delay = 0) => {
      if (!running) return;
      if (detectionTimer) clearTimeout(detectionTimer);
      detectionTimer = setTimeout(async () => {
        detectionTimer = null;
        await analyzeFrame();
        if (running) scheduleAnalysis(DETECTION_INTERVAL_MS);
      }, delay);
    };

    const loadModel = async () => {
      modelState.textContent = "Chargement…";
      if (yoloRuntimeReady()) {
        try {
          model = await window.YoloDetector.create({
            modelUrl: root.dataset.yoloModelUrl,
            wasmUrl: root.dataset.yoloWasmUrl
          });
          modelState.textContent = "YOLO11n prêt — détection instantanée";
          return;
        } catch (error) {
          console.warn("YOLO indisponible, repli COCO-SSD", error);
        }
      }
      await ensureVisionRuntime();
      await window.tf.ready();
      model = await window.cocoSsd.load({base: "lite_mobilenet_v2"});
      modelState.textContent = "COCO-SSD de secours (classe person)";
    };

    function stopCamera() {
      running = false;
      if (stream) stream.getTracks().forEach(track => track.stop());
      stream = null;
      video.srcObject = null;
      context.clearRect(0, 0, overlay.width, overlay.height);
      cameraOff.hidden = false;
      liveIndicator.hidden = true;
      startButton.disabled = !credentials;
      stopButton.disabled = true;
      if (detectionTimer) clearTimeout(detectionTimer);
      detectionTimer = null;
    }

    startButton.addEventListener("click", async () => {
      if (!credentials) return;
      startButton.disabled = true;
      setStatus("Demande d’autorisation de la webcam…");
      try {
        stream = await requestCameraStream();
        video.srcObject = stream;
        await video.play();
        running = true;
        cameraOff.hidden = true;
        liveIndicator.hidden = false;
        stopButton.disabled = false;
        setStatus("Webcam active. Analyse et aperçu locaux uniquement.");
        try { await loadModel(); } catch (error) { modelState.textContent = "Indisponible — simulation disponible"; setStatus(error.message, true); }
        scheduleAnalysis();
        await heartbeat();
      } catch (error) {
        stopCamera();
        setStatus(webcamErrorMessage(error), true);
      }
    });

    stopButton.addEventListener("click", () => { stopCamera(); setStatus("Webcam arrêtée immédiatement."); });
    simulationButton.addEventListener("click", () => transmitEvent(1, true));
    window.addEventListener("beforeunload", stopCamera);

    try {
      credentials = await readCredentials();
      if (!credentials) {
        startButton.disabled = true;
        simulationButton.disabled = true;
        pairingLink.hidden = false;
        setStatus("Aucune identité caméra dans ce navigateur.", true);
        return;
      }
      setStatus("Identité caméra trouvée. La webcam attend votre autorisation.");
      await refreshState();
      stateTimer = setInterval(refreshState, 5000);
      heartbeatTimer = setInterval(heartbeat, 30000);
    } catch (error) {
      startButton.disabled = true;
      simulationButton.disabled = true;
      pairingLink.hidden = false;
      setStatus("Impossible de lire l’identité locale de la caméra.", true);
    }
  });
})();
