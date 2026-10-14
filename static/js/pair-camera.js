(() => {
  "use strict";

  const data = document.getElementById("camera-credentials");
  const status = document.getElementById("credential-status");
  if (!data || !status) return;

  const credentials = JSON.parse(data.textContent);
  credentials.pairedAt = Date.now();
  const request = indexedDB.open("sentinelle-camera", 1);
  request.onupgradeneeded = () => {
    const database = request.result;
    if (!database.objectStoreNames.contains("credentials")) {
      database.createObjectStore("credentials", {keyPath: "cameraId"});
    }
  };
  request.onerror = () => {
    status.textContent = "Le navigateur n’a pas pu conserver l’identité. Recommencez l’appairage dans un navigateur compatible.";
    status.classList.add("error");
  };
  request.onsuccess = () => {
    const transaction = request.result.transaction("credentials", "readwrite");
    transaction.objectStore("credentials").put(credentials);
    transaction.oncomplete = () => {
      status.textContent = "Identité enregistrée. La webcam est prête à être activée avec votre consentement.";
    };
    transaction.onerror = () => {
      status.textContent = "Échec de l’enregistrement local de l’identité caméra.";
      status.classList.add("error");
    };
  };
})();
