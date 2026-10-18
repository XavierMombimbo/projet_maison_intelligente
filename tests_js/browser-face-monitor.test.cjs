const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto').webcrypto;

async function monitor() {
  const nodes = {}, events = {}, timers = [];
  const ctx = new Proxy({}, {get: (target, key) => target[key] || (() => {})});
  const make = () => ({textContent: '', hidden: false, disabled: false, handlers: {},
    classList: {toggle() {}, remove() {}}, addEventListener(k, f) {this.handlers[k] = f;},
    querySelector: () => ({value: 'csrf'}), getContext: () => ctx,
    readyState: 4, videoWidth: 1280, videoHeight: 720, play: async () => {},
    toBlob: fn => fn(new Blob(['synthetic-image'], {type: 'image/jpeg'}))});
  const root = make(); root.dataset = {browserContext: 'session', browserContextUrl: '/context/',
    stateUrl: '/state/', heartbeatUrl: '/heartbeat/', detectionUrl: '/detection/', faceRecognition: 'true'};
  let ready, responseResolve, sentResolve, stopped = 0;
  const sent = new Promise(resolve => {sentResolve = resolve;});
  const pending = new Promise(resolve => {responseResolve = resolve;});
  const response = body => ({ok: true, status: 200, headers: {get: name => name === 'Content-Type' ? 'application/json' : null}, json: async () => body});
  const document = {addEventListener: (_, fn) => {ready = fn;}, createElement: make,
    getElementById: id => id === 'camera-monitor' ? root : (nodes[id] ||= make())};
  const window = {crypto, isSecureContext: true, location: {origin: 'https://example.test'},
    addEventListener: (k, fn) => {events[k] = fn;},
    SentinelleBrowserCameraStore: {read: async () => ({cameraId: 'own'})},
    ort: {InferenceSession: {}}, YoloDetector: {create: async () => ({detect: async () => [
      {class: 'person', score: .9, bbox: [0, 0, 1000, 700]}
    ]})}};
  const context = vm.createContext({window, document, crypto, URL, Headers, Blob, FormData, TextEncoder, Date,
    atob, performance, console, navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop() {stopped++;}}]})}},
    setInterval: () => 1, clearInterval() {}, setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout() {},
    fetch: async (url, options) => {
      if (String(url).includes('camera=own')) return response({access_token: 'fixture', event_signing_key: 'key'});
      if (url === '/context/') return response({camera_ids: ['own']});
      if (url === '/detection/') {sentResolve(options); return pending;}
      return response({name: 'Fixture', monitoring_active: true, analysis: {presence_seconds: .01}});
    }});
  for (const name of ['detection-policy.js', 'temporal-tracker.js', 'detection-rules.js', 'event-contract-v2.js', 'browser-face-result.js', 'camera-monitor.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8'), context);
  }
  window.SentinelleEventV2 = context.SentinelleEventV2;
  await ready(); await nodes['start-camera'].handlers.click();
  // Establish presence, then let the real tracker satisfy its duration rule.
  await timers.shift()();
  await new Promise(resolve => setTimeout(resolve, 30));
  const analysis = timers.shift()();
  let timeout;
  try {
    await Promise.race([sent, new Promise((_, reject) => {
      timeout = setTimeout(() => reject(new Error(JSON.stringify({
        status: nodes['camera-status'].textContent, model: nodes['model-state'].textContent,
        face: nodes['face-result'].textContent, tracks: nodes['stability-state'].textContent,
      }))), 3000);
    })]);
  } finally { clearTimeout(timeout); }
  return {nodes, events, analysis, stopped: () => stopped,
    finish: () => responseResolve(response({notification_sent: false,
      face_verification: {state: 'recognized', reason: 'matched', source: 'server'}}))};
}

test('real monitor event flow displays server recognition and silence', async () => {
  const app = await monitor();
  assert.match(app.nodes['face-result'].textContent, /Vérification de la capture/);
  app.finish(); await app.analysis;
  assert.match(app.nodes['face-result'].textContent, /Profil reconnu.*silencieuse/);
  assert.match(app.nodes['camera-status'].textContent, /sans notification/);
});
test('stopping or changing account discards a late recognition response', async () => {
  for (const action of ['stop', 'account']) {
    const app = await monitor();
    if (action === 'stop') app.nodes['stop-camera'].handlers.click();
    else app.events['sentinelle:account-changed']();
    app.finish(); await app.analysis;
    assert.equal(app.stopped(), 1);
    assert.doesNotMatch(app.nodes['face-result'].textContent, /Profil reconnu/);
    assert.match(app.nodes['face-result'].textContent, /Webcam arrêtée/);
  }
});
