(function (global) {
  "use strict";
  const describe = result => {
    if (result.person_weapon_suspicion === true) return "Personne détectée avec port d’arme probable";
    if (result.combined && result.alert_title) return result.alert_title;
    if (result.state === "suspected") return "Suspicion d’arme";
    if (result.state === "candidate") return "Objet à vérifier";
    if (result.state === "clear") return "Aucune suspicion sur cette image";
    return "Analyse indisponible";
  };
  function create({send, render, onResult = () => {}, now = () => Date.now(), newId = () => global.crypto.randomUUID()}) {
    let enabled = false, busy = false, generation = 0, next = 0, runId = "";
    return {
      start() {
        enabled = true; generation++; next = 0; runId = newId();
        render("Analyse en cours…", "running");
      },
      stop() {
        enabled = false; generation++; runId = "";
        onResult(null);
        render("Arrêté", "stopped");
      },
      async sample(capture, active) {
        if (!enabled || busy || now() < next || !active()) return;
        const ownGeneration = generation, ownRun = runId;
        busy = true; next = now() + 1500;
        try {
          const blob = await capture();
          if (!enabled || generation !== ownGeneration || !active()) return;
          const result = await send(blob, newId(), ownRun);
          if (!enabled || generation !== ownGeneration || !active()) return;
          onResult(result);
          render(describe(result), result.state);
        } catch (_) {
          if (enabled && generation === ownGeneration && active()) {
            next = now() + 5000;
            onResult(null);
            render(describe({state: "unavailable"}), "unavailable");
          }
        } finally { busy = false; }
      }
    };
  }
  global.SentinelleWeaponReview = {create, describe};
})(typeof window === "undefined" ? globalThis : window);
