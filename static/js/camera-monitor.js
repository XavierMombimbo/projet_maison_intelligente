(() => {
  "use strict";

  const DB_NAME = "sentinelle-camera";
  const STORE_NAME = "credentials";
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

  const readCredentials = async (requestedCameraId = "") => {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const store = database.transaction(STORE_NAME).objectStore(STORE_NAME);
      const request = requestedCameraId ? store.get(requestedCameraId) : store.getAll();
      request.onsuccess = () => {
        if (requestedCameraId) {
          resolve(request.result || null);
          return;
        }
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

  const signDetection = async ({
    credentials, path, timestamp, nonce, eventId, observedAt,
    modelName, modelVersion, objects, blob, ruleContext
  }) => {
    if (!credentials.eventSigningKey || !window.crypto?.subtle) {
      throw new Error("La signature cryptographique de la caméra est indisponible.");
    }
    const encoder = new TextEncoder();
    const captureDigest = bytesToHex(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())));
    const payload = window.SentinelleEventV2.signaturePayload({
      method: "POST",
      path,
      cameraId: credentials.cameraId,
      timestamp,
      nonce,
      eventId,
      observedAt,
      modelName,
      modelVersion,
      objects,
      simulated: false,
      captureType: blob.type,
      captureDigest,
      ruleContext
    });
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
    const cameraStatus = document.getElementById("camera-status");
    const monitoringState = document.getElementById("monitoring-state");
    const modelState = document.getElementById("model-state");
    const stabilityState = document.getElementById("stability-state");
    const analysisState = document.getElementById("analysis-state");
    const rulesState = document.getElementById("rules-state");
    const thresholdsState = document.getElementById("thresholds-state");
    const analysisSettingsLink = document.getElementById("analysis-settings-link");
    const monitoringToggleForm = document.getElementById("monitoring-toggle-form");
    const monitoringToggleButton = document.getElementById("monitoring-toggle-button");
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
    let cooldownUntil = 0;
    let detectionTimer = null;
    let stateTimer = null;
    let heartbeatTimer = null;
    let serverClockOffsetMs = 0;
    let modelDescriptor = null;
    let lastInferenceAt = 0;
    let modelFailed = false;
    let analysisConfig = {
      zone: {x: 0, y: 0, width: 1, height: 1},
      line: null,
      presenceSeconds: 1,
      forbiddenCrossingDirection: "any",
      alertThresholds: {person: 0.45, dog: 0.50, cat: 0.50},
      groupingWindowSeconds: 30
    };
    const tracker = new window.SentinelleTemporalTracker();

    const synchronizeServerClock = (response, requestStartedAt) => {
      const serverTimestamp = Number(response.headers.get("X-Sentinelle-Time"));
      if (!Number.isFinite(serverTimestamp) || serverTimestamp <= 0) return;
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

    const networkErrorMessage = (error) => {
      if (error instanceof TypeError && /fetch/i.test(error.message || "")) {
        return "Serveur local inaccessible. Vérifiez que Django tourne toujours sur cette adresse, puis rechargez la page.";
      }
      return error.message || "Communication impossible avec le serveur local.";
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
      return `Impossible de démarrer la webcam (${error?.name || "erreur inconnue"}).`;
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
      let response = null;
      try {
        response = await fetch(root.dataset.tokenUrl, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({device_id: credentials.deviceId, device_secret: credentials.deviceSecret})
        });
      } catch (error) {
        throw new Error(networkErrorMessage(error));
      }
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
      let response = null;
      try {
        response = await fetch(url, {...options, headers});
      } catch (error) {
        throw new Error(networkErrorMessage(error));
      }
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
        const nextAnalysisConfig = {
          zone: state.analysis?.zone || {x: 0, y: 0, width: 1, height: 1},
          line: state.analysis?.line || null,
          presenceSeconds: Number(state.analysis?.presence_seconds) || 1,
          forbiddenCrossingDirection: state.analysis?.forbidden_crossing_direction || "any",
          alertThresholds: state.analysis?.alert_thresholds || {person: 0.45, dog: 0.50, cat: 0.50},
          groupingWindowSeconds: Number(state.analysis?.grouping_window_seconds) || 30
        };
        if (JSON.stringify(nextAnalysisConfig) !== JSON.stringify(analysisConfig)) tracker.reset();
        analysisConfig = nextAnalysisConfig;
        const zone = analysisConfig.zone;
        analysisState.textContent = `x ${Math.round(zone.x * 100)} % · y ${Math.round(zone.y * 100)} % · ${Math.round(zone.width * 100)} × ${Math.round(zone.height * 100)} %`;
        rulesState.textContent = `${analysisConfig.line ? "Ligne active" : "Ligne inactive"} · présence ${analysisConfig.presenceSeconds.toFixed(1)} s · regroupement ${analysisConfig.groupingWindowSeconds} s`;
        thresholdsState.textContent = `Personne ≥ ${Math.round(analysisConfig.alertThresholds.person * 100)} % · Chien ≥ ${Math.round(analysisConfig.alertThresholds.dog * 100)} % · Chat ≥ ${Math.round(analysisConfig.alertThresholds.cat * 100)} %`;
        analysisSettingsLink.href = state.analysis_settings_url;
        analysisSettingsLink.hidden = false;
        monitoringToggleForm.action = state.monitoring_toggle_url;
        monitoringToggleForm.hidden = false;
        monitoringToggleButton.textContent = monitoringActive
          ? "Désactiver la surveillance de cette caméra"
          : "Activer la surveillance de cette caméra";
        document.getElementById("camera-title").textContent = state.name;
        monitoringState.textContent = monitoringActive ? "Surveillance activée" : "Surveillance désactivée";
        monitoringState.classList.toggle("active", monitoringActive);
        if (!monitoringActive) {
          tracker.reset();
          stabilityState.textContent = "0 piste dans la zone";
        }
      } catch (error) {
        monitoringActive = false;
        if (error.code === "INVALID_CREDENTIALS" && credentials) {
          await deleteCredentials(credentials.cameraId).catch(() => {});
          credentials = null;
          pairingLink.hidden = false;
        }
        setStatus(error.message, true);
        stopCamera();
      }
    };

    const heartbeat = async () => {
      if (!credentials) return;
      const analysisState = modelFailed ? "failed" : (
        !running || !monitoringActive ? "inactive" : (
          model && Date.now() - lastInferenceAt <= 10000 ? "running" : "stalled"
        )
      );
      try {
        await cameraFetch(root.dataset.heartbeatUrl, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({analysis_state: analysisState})
        });
      } catch (_) { /* next state poll reports it */ }
    };

    const drawPredictions = (predictions) => {
      overlay.width = video.videoWidth || 640;
      overlay.height = video.videoHeight || 360;
      context.clearRect(0, 0, overlay.width, overlay.height);
      const zone = analysisConfig.zone;
      context.save();
      context.strokeStyle = "#22d3ee";
      context.lineWidth = 3;
      context.setLineDash([10, 7]);
      context.strokeRect(
        zone.x * overlay.width + 2,
        zone.y * overlay.height + 2,
        Math.max(0, zone.width * overlay.width - 4),
        Math.max(0, zone.height * overlay.height - 4)
      );
      if (analysisConfig.line) {
        context.strokeStyle = "#f472b6";
        context.setLineDash([7, 5]);
        context.beginPath();
        context.moveTo(analysisConfig.line.x1 * overlay.width, analysisConfig.line.y1 * overlay.height);
        context.lineTo(analysisConfig.line.x2 * overlay.width, analysisConfig.line.y2 * overlay.height);
        context.stroke();
      }
      context.restore();
      context.lineWidth = 4;
      context.font = "18px system-ui";
      window.SentinelleDetectionPolicy.acceptedPredictions(predictions).forEach(item => {
        const settings = window.SentinelleDetectionPolicy.classes[item.class];
        const [x, y, width, height] = item.bbox;
        context.strokeStyle = settings.color;
        context.fillStyle = settings.color;
        context.strokeRect(x, y, width, height);
        const trackLabel = item.trackId ? ` #${item.trackId.replace("track-", "")}` : "";
        const durationLabel = item.insideZone ? ` · ${item.zoneDurationSeconds.toFixed(1)}s` : " · hors zone";
        context.fillText(`${settings.label}${trackLabel} ${Math.round(item.score * 100)}%${durationLabel}`, x, Math.max(20, y - 8));
      });
    };

    const trackPredictions = (predictions) => {
      const width = Math.max(video.videoWidth, 1);
      const height = Math.max(video.videoHeight, 1);
      const normalized = predictions.map((item, sourceIndex) => ({
        class: item.class,
        score: item.score,
        sourceIndex,
        bbox: [
          item.bbox[0] / width,
          item.bbox[1] / height,
          item.bbox[2] / width,
          item.bbox[3] / height
        ]
      }));
      return tracker.update(normalized, performance.now(), analysisConfig.zone, analysisConfig.line).map(item => ({
        ...predictions[item.sourceIndex],
        trackId: item.trackId,
        trackDurationSeconds: item.trackDurationSeconds,
        zoneDurationSeconds: item.zoneDurationSeconds,
        insideZone: item.insideZone,
        crossingDirection: item.crossingDirection
      }));
    };

    const frameBlob = () => new Promise((resolve) => {
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
      canvas.toBlob(resolve, "image/jpeg", .72);
    });

    const normalizedObjects = (predictions) => {
      const width = Math.max(video.videoWidth, 1);
      const height = Math.max(video.videoHeight, 1);
      return predictions.slice(0, 64).map(item => {
        const [x, y, boxWidth, boxHeight] = item.bbox;
        const normalizedX = Math.max(0, Math.min(1, x / width));
        const normalizedY = Math.max(0, Math.min(1, y / height));
        const object = {
          label: item.class.toLowerCase().replace(/[^a-z0-9._-]/g, "_"),
          confidence: item.score,
          bbox: [
            normalizedX,
            normalizedY,
            Math.max(0.000001, Math.min(1 - normalizedX, boxWidth / width)),
            Math.max(0.000001, Math.min(1 - normalizedY, boxHeight / height))
          ]
        };
        if (item.trackId) object.track_id = item.trackId;
        return object;
      });
    };

    const transmitEvent = async (predictions, ruleContext) => {
      if (!monitoringActive) {
        setStatus("Activez d’abord la surveillance depuis le compte propriétaire.", true);
        return;
      }
      cooldownUntil = Date.now() + EVENT_COOLDOWN_MS;
      const blob = await frameBlob();
      const eventId = crypto.randomUUID();
      const observedAt = new Date(Date.now() + serverClockOffsetMs).toISOString();
      const objects = normalizedObjects(predictions);
      const descriptor = modelDescriptor;
      const formData = new FormData();
      formData.append("contract_version", "2");
      formData.append("event_id", eventId);
      formData.append("observed_at", observedAt);
      formData.append("model_name", descriptor.name);
      formData.append("model_version", descriptor.version);
      formData.append("objects", JSON.stringify(objects));
      formData.append("rule_context", JSON.stringify(ruleContext));
      formData.append("capture", blob, "detection.jpg");
      try {
        let response = null;
        let transportError = null;
        for (let attempt = 0; attempt < 2; attempt += 1) {
          await validToken();
          const requestNonce = crypto.randomUUID();
          const requestTimestamp = Math.floor((Date.now() + serverClockOffsetMs) / 1000);
          const signature = await signDetection({
            credentials,
            path: new URL(root.dataset.detectionUrl, window.location.origin).pathname,
            timestamp: requestTimestamp,
            nonce: requestNonce,
            eventId,
            observedAt,
            modelName: descriptor.name,
            modelVersion: descriptor.version,
            objects,
            blob,
            ruleContext
          });
          try {
            response = await cameraFetch(root.dataset.detectionUrl, {
              method: "POST",
              headers: {
                "X-Camera-Timestamp": String(requestTimestamp),
                "X-Camera-Nonce": requestNonce,
                "X-Camera-Signature": signature
              },
              body: formData
            }, false);
          } catch (error) {
            transportError = error;
            if (attempt === 0) continue;
            throw error;
          }
          if (response.status >= 500 && attempt === 0) continue;
          break;
        }
        if (!response) throw transportError || new Error("Échec de la transmission.");
        if (response.status === 429) {
          const retryAfter = Number(response.headers.get("Retry-After"));
          if (Number.isFinite(retryAfter) && retryAfter > 0) {
            cooldownUntil = Date.now() + Math.max(EVENT_COOLDOWN_MS, retryAfter * 1000);
          }
        }
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Échec de la transmission.");
        cooldownUntil = Date.now() + EVENT_COOLDOWN_MS;
        const ruleLabel = ruleContext.type === "line_crossing" ? "Franchissement" : "Présence prolongée";
        lastEvent.textContent = `${ruleLabel} ${body.deduplicated ? "confirmé" : "envoyé"} à ${new Date().toLocaleTimeString()}`;
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
        lastInferenceAt = Date.now();
        const accepted = window.SentinelleDetectionPolicy.acceptedPredictions(
          predictions,
          analysisConfig.alertThresholds
        );
        const tracked = trackPredictions(accepted);
        drawPredictions(tracked);
        const inside = tracked.filter(item => item.insideZone);
        stabilityState.textContent = `${inside.length} piste${inside.length === 1 ? "" : "s"} dans la zone · seuil ${analysisConfig.presenceSeconds.toFixed(1)} s`;
        const ruleMatch = window.SentinelleRuleEvaluator.evaluate(tracked, analysisConfig);
        if (Date.now() >= cooldownUntil && ruleMatch) {
          await transmitEvent(ruleMatch.predictions, ruleMatch.context);
        }
      } catch (error) {
        modelFailed = true;
        model = null;
        modelDescriptor = null;
        tracker.reset();
        context.clearRect(0, 0, overlay.width, overlay.height);
        modelState.textContent = "Indisponible — aucune détection";
        setStatus("Le modèle IA a échoué. La webcam reste en aperçu, mais aucun événement n’est détecté ni envoyé.", true);
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
          modelDescriptor = {name: "yolo11n", version: "320@18eac4f9d291"};
          modelFailed = false;
          modelState.textContent = "YOLO11n 320 prêt — personne, chien, chat";
          return;
        } catch (error) {
          console.warn("YOLO indisponible, repli COCO-SSD", error);
        }
      }
      await ensureVisionRuntime();
      await window.tf.ready();
      model = await window.cocoSsd.load({base: "lite_mobilenet_v2"});
      modelDescriptor = {name: "coco-ssd", version: "2.2.3-lite_mobilenet_v2"};
      modelFailed = false;
      modelState.textContent = "COCO-SSD prêt — personne, chien, chat";
    };

    function stopCamera() {
      running = false;
      lastInferenceAt = 0;
      modelFailed = false;
      if (stream) stream.getTracks().forEach(track => track.stop());
      stream = null;
      tracker.reset();
      video.srcObject = null;
      context.clearRect(0, 0, overlay.width, overlay.height);
      cameraOff.hidden = false;
      liveIndicator.hidden = true;
      startButton.disabled = !credentials;
      stopButton.disabled = true;
      if (detectionTimer) clearTimeout(detectionTimer);
      detectionTimer = null;
      stabilityState.textContent = "0 piste dans la zone";
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
        try {
          await loadModel();
        } catch (error) {
          modelFailed = true;
          model = null;
          modelDescriptor = null;
          modelState.textContent = "Indisponible — aucune détection";
          setStatus(`${error.message} La webcam reste en aperçu, mais aucun événement ne sera envoyé.`, true);
        }
        scheduleAnalysis();
        await heartbeat();
      } catch (error) {
        stopCamera();
        setStatus(webcamErrorMessage(error), true);
      }
    });

    stopButton.addEventListener("click", () => { stopCamera(); heartbeat(); setStatus("Webcam arrêtée immédiatement."); });
    window.addEventListener("beforeunload", stopCamera);

    try {
      const requestedCameraId = root.dataset.requestedCameraId || "";
      credentials = await readCredentials(requestedCameraId);
      if (!credentials) {
        startButton.disabled = true;
        pairingLink.hidden = false;
        setStatus(
          requestedCameraId
            ? "Cette caméra n’est pas appairée dans ce navigateur. Appairez-la avant de lancer la mesure."
            : "Aucune identité caméra dans ce navigateur.",
          true
        );
        return;
      }
      setStatus("Identité caméra trouvée. La webcam attend votre autorisation.");
      await refreshState();
      stateTimer = setInterval(refreshState, 5000);
      heartbeatTimer = setInterval(heartbeat, 30000);
    } catch (error) {
      startButton.disabled = true;
      pairingLink.hidden = false;
      setStatus("Impossible de lire l’identité locale de la caméra.", true);
    }
  });
})();
