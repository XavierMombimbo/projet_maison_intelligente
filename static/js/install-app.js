(() => {
  let installPrompt;
  const buttons = document.querySelectorAll('[data-install-app]');
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    installPrompt = event;
    buttons.forEach((button) => { button.hidden = false; });
  });
  buttons.forEach((button) => button.addEventListener('click', async () => {
    if (!installPrompt) return;
    await installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    buttons.forEach((item) => { item.hidden = true; });
  }));
  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    buttons.forEach((button) => { button.hidden = true; });
  });
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  }
})();
