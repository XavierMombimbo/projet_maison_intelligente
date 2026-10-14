(() => {
  const root = document.getElementById("mobile-api-test");
  if (!root) return;

  const byId = (id) => document.getElementById(id);
  const status = byId("mobile-test-status");
  const state = { challenge: "", access: "", refresh: "", sessionId: "" };
  const storedDeviceKey = "sentinelle-mobile-test-device-id";

  const showStatus = (message, error = false) => {
    status.hidden = false;
    status.textContent = message;
    status.classList.toggle("warning", error);
  };

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (_error) { payload = {}; }
    if (!response.ok) throw new Error(payload.detail || `Erreur HTTP ${response.status}`);
    return payload;
  };

  const post = (url, payload, token = "") => requestJson(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  const get = (url) => requestJson(url, {
    headers: { Authorization: `Bearer ${state.access}` },
  });

  const getDeviceId = () => {
    let value = window.localStorage.getItem(storedDeviceKey);
    if (!value) {
      value = `browser-${crypto.randomUUID()}`;
      window.localStorage.setItem(storedDeviceKey, value);
    }
    return value;
  };

  byId("mobile-login-button").addEventListener("click", async () => {
    showStatus("Vérification du mot de passe…");
    try {
      const result = await post(root.dataset.loginUrl, {
        identifier: byId("mobile-identifier").value,
        password: byId("mobile-password").value,
        device_id: getDeviceId(),
        device_name: byId("mobile-device-name").value,
      });
      state.challenge = result.challenge;
      byId("mobile-email-status").textContent = result.email_sent
        ? `Code envoyé à ${result.email}.`
        : "L’e-mail n’a pas pu être envoyé. Utilisez votre application MFA ou un code de récupération.";
      byId("mobile-mfa-step").hidden = false;
      byId("mobile-code").focus();
      showStatus("Mot de passe validé. Aucun jeton n’a été délivré avant le MFA.");
    } catch (error) {
      showStatus(error.message, true);
    }
  });

  byId("mobile-mfa-button").addEventListener("click", async () => {
    showStatus("Validation du code MFA…");
    try {
      const tokens = await post(root.dataset.mfaUrl, {
        challenge: state.challenge,
        code: byId("mobile-code").value,
      });
      state.access = tokens.access_token;
      state.refresh = tokens.refresh_token;
      state.sessionId = tokens.session_id;
      const [me, houses, cameras, events] = await Promise.all([
        get(root.dataset.meUrl), get(root.dataset.housesUrl),
        get(root.dataset.camerasUrl), get(root.dataset.eventsUrl),
      ]);
      byId("mobile-data-summary").textContent =
        `${me.email} · ${houses.count} maison(s) · ${cameras.count} caméra(s) · ${events.count} événement(s).`;
      byId("mobile-success-step").hidden = false;
      showStatus("Connexion MFA réussie et données filtrées chargées.");
    } catch (error) {
      showStatus(error.message, true);
    }
  });

  byId("mobile-refresh-button").addEventListener("click", async () => {
    showStatus("Renouvellement de la session…");
    try {
      const tokens = await post(root.dataset.refreshUrl, { refresh_token: state.refresh });
      state.access = tokens.access_token;
      state.refresh = tokens.refresh_token;
      showStatus("Jetons renouvelés. L’ancien jeton de renouvellement est maintenant invalide.");
    } catch (error) {
      showStatus(error.message, true);
    }
  });

  byId("mobile-revoke-button").addEventListener("click", async () => {
    showStatus("Révocation de la session…");
    try {
      const response = await fetch(
        `${root.dataset.sessionBase}${encodeURIComponent(state.sessionId)}/revoke/`,
        { method: "POST", headers: { Authorization: `Bearer ${state.access}` } },
      );
      if (!response.ok) throw new Error(`Erreur HTTP ${response.status}`);
      state.access = "";
      state.refresh = "";
      showStatus("Session révoquée. Ses jetons ne donnent plus accès à l’API.");
    } catch (error) {
      showStatus(error.message, true);
    }
  });
})();
