/* Only pairing metadata belongs on disk. Session grants remain in memory. */
(() => {
  "use strict";
  const open = () => new Promise((resolve, reject) => {
    const request = indexedDB.open("sentinelle-camera", 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("credentials")) request.result.createObjectStore("credentials", {keyPath: "cameraId"});
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const metadata = value => ({cameraId: String(value.cameraId), pairedAt: Number(value.pairedAt) || 0});
  const read = async (allowedIds, requestedId = "") => {
    const database = await open();
    return new Promise((resolve, reject) => {
      const tx = database.transaction("credentials", "readwrite");
      const store = tx.objectStore("credentials");
      const request = store.getAll();
      let selected = null;
      request.onsuccess = () => {
        const rows = (request.result || []).map(metadata);
        rows.forEach(row => store.put(row));
        const allowed = new Set(allowedIds.map(String));
        const candidates = rows.filter(row => allowed.has(row.cameraId) && (!requestedId || row.cameraId === requestedId));
        candidates.sort((a, b) => b.pairedAt - a.pairedAt);
        selected = candidates[0] || null;
      };
      tx.oncomplete = () => {database.close(); resolve(selected);};
      tx.onerror = () => {database.close(); reject(tx.error);};
      tx.onabort = tx.onerror;
    });
  };
  const save = async value => {
    const database = await open();
    return new Promise((resolve, reject) => {
      const tx = database.transaction("credentials", "readwrite");
      tx.objectStore("credentials").put(metadata(value));
      tx.oncomplete = () => {database.close(); resolve();};
      tx.onerror = () => {database.close(); reject(tx.error);};
    });
  };
  window.SentinelleBrowserCameraStore = {read, save};
})();
