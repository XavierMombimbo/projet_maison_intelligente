(() => {
  "use strict";
  const reasons = {
    disabled: "Reconnaissance non activée sur ce serveur",
    no_person: "Aucune personne dans cet événement",
    no_profiles: "Aucun profil facial actif dans cette maison",
    multiple_people: "Plusieurs personnes : vérification non déterminée",
    quality: "Visage non exploitable : placez-vous seul, de face et bien éclairé",
    busy: "Vérification occupée ; nouvel essai au prochain événement",
    profile_changed: "Profil modifié ou retiré ; vérification non déterminée",
  };
  window.SentinelleBrowserFaceResult = {
    describe(body) {
      const result = body?.face_verification;
      if (!result || result.source !== "server") return "Vérification faciale indisponible";
      if (result.state === "recognized") return body.notification_sent === false
        ? "Profil reconnu · présence silencieuse"
        : "Profil reconnu · alerte maintenue par la règle de surveillance";
      if (result.state === "unknown") return "Personne non reconnue";
      return reasons[result.reason] || "Vérification faciale indisponible";
    }
  };
})();
