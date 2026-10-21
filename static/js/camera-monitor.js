(() => {
  "use strict";

  const DETECTION_INTERVAL_MS = 350;
  const EVENT_COOLDOWN_MS = 15000;

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
    const faceResult = document.getElementById("face-result");
    const faceEnabled = root.dataset.faceRecognition === "true";
    const weaponToggle = document.getElementById("weapon-review-toggle");
    const weaponResult = document.getElementById("weapon-result");
    const weaponHelp = document.getElementById("weapon-help");
    const weaponStartButton = document.getElementById("start-weapon-test");
    const weaponStopButton = document.getElementById("stop-weapon-test");
    const weaponDemoNotice = document.getElementById("weapon-demo-notice");
    const weaponDemoLink = document.getElementById("weapon-demo-link");
    let weaponDemoSelected = false;
    let weaponStarting = false;
    let cameraGeneration = 0;
    const showWeaponResult = (text, state = "stopped") => {
      if (weaponResult) { weaponResult.textContent = text; weaponResult.dataset.state = state; }
      const hints = {
        stopped: root.dataset.weaponAcademicDemo === "true" ? "Cliquez sur Démarrer la démo." : "Cliquez sur Démarrer le test.",
        starting: "Autorisez la webcam si le navigateur vous le demande.",
        running: "Montrez une image de test ou un objet factice à la webcam.",
        candidate: "Gardez le support immobile quelques secondes.",
        suspected: "Un objet ressemble à une arme. Vérifiez la vidéo ci-dessous.",
        clear: "L’analyse continue. Cela ne garantit pas l’absence d’arme.",
        unavailable: "L’analyse n’a pas abouti. Une nouvelle tentative suivra.",
        paused: "Activez la surveillance dans Autres réglages.",
        camera_error: "Autorisez la webcam pour cette page, puis réessayez."
      };
      if (weaponHelp) weaponHelp.textContent = hints[state] || "";
    };
    const updateWeaponButtons = () => {
      if (weaponStartButton) weaponStartButton.disabled = !credentials || invalidated || weaponStarted || weaponStarting;
      if (weaponStopButton) weaponStopButton.disabled = !weaponStarted && !weaponStarting && !(running && weaponToggle?.checked);
    };
    let weaponDetections = [], latestPredictions = [];
    let weaponResultAt = 0;
    let weaponStarted = false;
    const weaponReview = root.dataset.weaponEnabled === "true" && window.SentinelleWeaponReview
      ? window.SentinelleWeaponReview.create({
        send: async (blob, eventId, runId) => {
          const eventStream = stream;
          await validToken();
          if (!running || invalidated || !monitoringActive || stream !== eventStream) throw new Error("Analyse arrêtée.");
          const observedAt = new Date(Date.now() + serverClockOffsetMs).toISOString();
          const timestamp = Math.floor((Date.now() + serverClockOffsetMs) / 1000);
          const nonce = crypto.randomUUID();
          const objects = [{label: "scene", confidence: 1, bbox: [0, 0, 1, 1]}];
          const modelName = weaponDemoSelected ? "weapon-observation-academic-demo" : "weapon-observation";
          const signature = await signDetection({credentials,
            path: new URL(root.dataset.weaponUrl, window.location.origin).pathname,
            timestamp, nonce, eventId, observedAt, modelName,
            modelVersion: runId, objects, blob, ruleContext: null});
          if (!running || invalidated || !monitoringActive || stream !== eventStream) throw new Error("Analyse arrêtée.");
          const form = new FormData();
          for (const [key, value] of Object.entries({contract_version: "2", event_id: eventId,
            observed_at: observedAt, model_name: modelName, model_version: runId,
            objects: JSON.stringify(objects)})) form.append(key, value);
          form.append("capture", blob, "observation.jpg");
          const response = await cameraFetch(root.dataset.weaponUrl, {method: "POST", body: form,
            headers: {"X-Camera-Timestamp": String(timestamp), "X-Camera-Nonce": nonce, "X-Camera-Signature": signature}}, false);
          if (!response.ok) throw new Error("Analyse d’arme indisponible.");
          return response.json();
        },
        render: showWeaponResult,
        onResult: result => {
          weaponDetections = result?.detections || [];
          weaponResultAt = Date.now();
          if (weaponDemoSelected && result?.academic_demo && result.event_id && weaponDemoNotice && weaponDemoLink
              && typeof result.detail_url === "string" && result.detail_url.startsWith("/") && !result.detail_url.startsWith("//")) {
            weaponDemoLink.href = result.detail_url;
            weaponDemoNotice.hidden = false;
          }
          if (running && !invalidated) drawPredictions(latestPredictions);
        }
      }) : null;
    const syncWeaponReview = () => {
      if (!weaponReview || !weaponToggle) return;
      if (!weaponToggle.checked || invalidated) {
        weaponStarted = false;
        weaponReview.stop();
        updateWeaponButtons();
        return;
      }
      if (!running || !monitoringActive) {
        if (weaponStarted) weaponReview.stop();
        weaponStarted = false;
        showWeaponResult(!running ? "Démarrez la webcam" : "Surveillance en pause", !running ? "stopped" : "paused");
        updateWeaponButtons();
        return;
      }
      if (!weaponStarted) {
        weaponStarted = true;
        weaponReview.start();
        updateWeaponButtons();
      }
    };
    weaponToggle?.addEventListener("change", syncWeaponReview);
    const cameraOff = document.getElementById("camera-off");
    const liveIndicator = document.getElementById("live-indicator");
    const pairingLink = document.getElementById("pairing-link");
    const controlStatusDot = document.getElementById("control-status-dot");

    let credentials = null;
    let invalidated = false;
    startButton.disabled = true;
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
        const url = new URL(root.dataset.browserContextUrl, window.location.origin);
        url.searchParams.set("camera", credentials.cameraId);
        response = await fetch(url, {
          credentials: "same-origin", cache: "no-store",
          headers: {"X-Sentinelle-Camera-Context": root.dataset.browserContext}
        });
      } catch (error) {
        throw new Error(networkErrorMessage(error));
      }
      synchronizeServerClock(response, requestStartedAt);
      if (!response.ok || response.redirected || !response.headers.get("Content-Type")?.includes("application/json")) {
        const error = new Error(
          [401, 403, 404, 409].includes(response.status) || response.redirected
            ? "Identité caméra expirée ou révoquée. Appairez de nouveau cet appareil."
            : "Le serveur n’a pas pu renouveler l’identité caméra."
        );
        error.code = response.status === 429 ? "TOKEN_RENEWAL_FAILED" : "INVALID_CREDENTIALS";
        throw error;
      }
      const body = await response.json();
      credentials.accessToken = body.access_token;
      credentials.eventSigningKey = body.event_signing_key;

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
      headers.set("X-Sentinelle-Camera-Context", root.dataset.browserContext);
      headers.set("X-CSRFToken", monitoringToggleForm.querySelector("[name=csrfmiddlewaretoken]").value);
      const requestStartedAt = Date.now();
      let response = null;
      try {
        response = await fetch(url, {...options, headers, credentials: "same-origin", cache: "no-store"});
      } catch (error) {
        throw new Error(networkErrorMessage(error));
      }
      synchronizeServerClock(response, requestStartedAt);
      if ([401, 403].includes(response.status) && retry) {
        await renewToken();
        return cameraFetch(url, options, false);
      }
      if ([401, 403].includes(response.status)) {
        const error = new Error("Cette caméra n’est plus autorisée pour votre session.");
        error.code = "INVALID_CREDENTIALS";
        throw error;
      }
      return response;
    };

    const refreshState = async () => {
      try {
        const response = await cameraFetch(root.dataset.stateUrl);
        if (!response.ok) throw new Error("La caméra ne peut plus lire son état.");
        const state = await response.json();
        if (!credentials || invalidated) return;
        startButton.disabled = running;
        updateWeaponButtons();
        monitoringActive = state.monitoring_active;
        if (weaponToggle?.checked) syncWeaponReview();
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
          invalidateSession();
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
      latestPredictions = predictions;
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
      if (Date.now() - weaponResultAt <= 5000) weaponDetections.slice(0, 64).forEach(item => {
        if (!['firearm', 'knife'].includes(item.label)) return;
        const [x, y, width, height] = item.bbox;
        context.strokeStyle = '#ad6821'; context.fillStyle = '#ad6821';
        context.strokeRect(x * overlay.width, y * overlay.height, width * overlay.width, height * overlay.height);
        context.fillText(item.label === 'firearm' ? 'Arme à feu ?' : 'Couteau ?',
          x * overlay.width, Math.max(20, y * overlay.height - 8));
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
      const scale = Math.min(1, (faceEnabled || weaponReview ? 1280 : 640) / Math.max(sourceWidth, 1));
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
      const eventStream = stream;
      const blob = await frameBlob();
      if (!running || invalidated || stream !== eventStream) return;
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
        if (faceEnabled && faceResult) faceResult.textContent = "Vérification de la capture…";
        let response = null;
        let transportError = null;
        for (let attempt = 0; attempt < 2; attempt += 1) {
          await validToken();
          if (!running || invalidated || stream !== eventStream) return;
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
          if (!running || invalidated || stream !== eventStream) return;
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
        if (!running || invalidated || stream !== eventStream) return;
        if (!response.ok) throw new Error(body.detail || "Échec de la transmission.");
        cooldownUntil = Date.now() + EVENT_COOLDOWN_MS;
        const ruleLabel = ruleContext.type === "line_crossing" ? "Franchissement" : "Présence prolongée";
        lastEvent.textContent = `${ruleLabel} ${body.deduplicated ? "confirmé" : "envoyé"} à ${new Date().toLocaleTimeString()}`;
        if (faceEnabled && faceResult) {
          faceResult.textContent = `${window.SentinelleBrowserFaceResult.describe(body)} · ${new Date().toLocaleTimeString()}`;
        }
        setStatus(body.face_verification?.state === "recognized" && body.notification_sent === false
          ? "Présence reconnue, enregistrée sans notification."
          : "Événement transmis ; le flux vidéo reste local.");
      } catch (error) {
        if (!running || invalidated || stream !== eventStream) return;
        if (faceEnabled && faceResult) faceResult.textContent = "Vérification indisponible : événement non confirmé";
        setStatus(error.message, true);
      }
    };

    const analyzeFrame = async () => {
      if (weaponReview) {
        // Separate failure boundary: an unavailable weapon model must not stop
        // normal detection, facial recognition or camera controls.
        void weaponReview.sample(frameBlob, () => running && monitoringActive && !invalidated);
      }
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
      cameraGeneration++;
      weaponStarting = false;
      weaponStarted = false;
      weaponReview?.stop();
      weaponDemoSelected = false;
      weaponDetections = []; latestPredictions = [];
      if (weaponToggle) weaponToggle.checked = false;
      updateWeaponButtons();
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
      if (faceEnabled && faceResult) faceResult.textContent = "Webcam arrêtée — aucune vérification en cours";
    }

    const startCamera = async () => {
      if (!credentials || invalidated) return;
      const ownGeneration = ++cameraGeneration;
      startButton.disabled = true;
      setStatus("Demande d’autorisation de la webcam…");
      try {
        await renewToken();
        if (!credentials || invalidated || ownGeneration !== cameraGeneration) return;
        const opened = await requestCameraStream();
        if (!credentials || invalidated || ownGeneration !== cameraGeneration) { opened.getTracks().forEach(track => track.stop()); return; }
        stream = opened;
        video.srcObject = stream;
        await video.play();
        if (!credentials || invalidated || ownGeneration !== cameraGeneration) { stopCamera(); return; }
        running = true;
        syncWeaponReview();
        cameraOff.hidden = true;
        liveIndicator.hidden = false;
        stopButton.disabled = false;
        setStatus(faceEnabled ? "Webcam active. La prochaine présence sera vérifiée sur le serveur."
          : "Webcam active. Analyse et aperçu locaux uniquement.");
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
        if (ownGeneration !== cameraGeneration) return;
        const weaponRequested = weaponToggle?.checked;
        stopCamera();
        if (error.code === "INVALID_CREDENTIALS") invalidateSession();
        else setStatus(webcamErrorMessage(error), true);
        if (weaponRequested) showWeaponResult("Webcam non disponible", "camera_error");
      }
    };
    startButton.addEventListener("click", startCamera);
    const startWeaponTest = async () => {
      if (!weaponReview || !credentials || invalidated || weaponStarting || weaponStarted) return;
      weaponDemoSelected = root.dataset.weaponAcademicDemo === "true";
      if (weaponDemoNotice) weaponDemoNotice.hidden = true;
      weaponToggle.checked = true;
      weaponStarting = true;
      updateWeaponButtons();
      showWeaponResult("Démarrage du test…", "starting");
      try {
        if (!running) await startCamera();
        else syncWeaponReview();
      } finally {
        weaponStarting = false;
        updateWeaponButtons();
      }
    };
    weaponStartButton?.addEventListener("click", () => startWeaponTest());
    weaponStopButton?.addEventListener("click", () => {
      stopCamera(); heartbeat(); setStatus("Webcam arrêtée.");
    });

    function invalidateSession() {
      invalidated = true;
      credentials = null;
      if (weaponDemoNotice) weaponDemoNotice.hidden = true;
      if (weaponDemoLink) weaponDemoLink.href = "#";
      stopCamera();
      if (stateTimer) clearInterval(stateTimer);
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      monitoringActive = false;
      monitoringToggleForm.hidden = true;
      analysisSettingsLink.hidden = true;
      document.getElementById("camera-title").textContent = "Mode caméra";
      monitoringState.textContent = "Session à vérifier";
      monitoringState.classList.remove("active");
      analysisState.textContent = rulesState.textContent = lastEvent.textContent = "—";
      setStatus("Le compte, la session ou les droits ont changé. Rechargez la page pour continuer.", true);
    }
    window.addEventListener("sentinelle:account-changed", invalidateSession);
    window.addEventListener("pageshow", event => { if (event.persisted) invalidateSession(); });
    window.addEventListener("pagehide", () => { stopCamera(); });
    stopButton.addEventListener("click", () => { stopCamera(); heartbeat(); setStatus("Webcam arrêtée immédiatement."); });
    window.addEventListener("beforeunload", stopCamera);

    try {
      const requestedCameraId = root.dataset.requestedCameraId || "";
      const authorization = await fetch(root.dataset.browserContextUrl, {
        credentials: "same-origin", cache: "no-store",
        headers: {"X-Sentinelle-Camera-Context": root.dataset.browserContext}
      });
      if (!authorization.ok || authorization.redirected || !authorization.headers.get("Content-Type")?.includes("application/json")) {
        invalidateSession(); return;
      }
      const permitted = await authorization.json();
      credentials = await window.SentinelleBrowserCameraStore.read(permitted.camera_ids, requestedCameraId);
      if (invalidated) { credentials = null; return; }
      if (!credentials) {
        startButton.disabled = true;
        monitoringState.textContent = "Aucune caméra autorisée";
        pairingLink.hidden = false;
        setStatus(
          requestedCameraId
            ? "Cette caméra n’est pas autorisée ou n’est pas appairée dans ce navigateur."
            : "Aucune caméra appairée n’est autorisée pour ce compte dans ce navigateur.",
          true
        );
        return;
      }
      await renewToken();
      await refreshState();
      if (!credentials || invalidated) return;
      setStatus("Caméra autorisée pour votre compte. La webcam attend votre accord.");
      stateTimer = setInterval(refreshState, 5000);
      heartbeatTimer = setInterval(heartbeat, 30000);
    } catch (error) {
      startButton.disabled = true;
      pairingLink.hidden = false;
      setStatus("Impossible de lire l’identité locale de la caméra.", true);
    }
  });
})();
