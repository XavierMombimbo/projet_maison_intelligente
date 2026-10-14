(() => {
  "use strict";

  // The TensorFlow UMD bundle extends an existing global namespace. Reset it on
  // this dedicated page so browser extensions or stale partial runtimes cannot
  // leave loadGraphModel unavailable.
  window.regeneratorRuntime = window.regeneratorRuntime || {};
  window.tf = {};
  window.cocoSsd = {};
})();
