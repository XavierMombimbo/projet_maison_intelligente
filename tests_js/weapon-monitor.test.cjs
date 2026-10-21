const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto').webcrypto;

async function monitor({useExistingCamera = false, stopDuringPermission = false, failPermission = false, monitoringActive = true,
                        academicDemo = false, demoUrl = '/demo-event/'} = {}) {
  const nodes = {}, events = {}, timers = [], labels = [];
  const ctx = new Proxy({fillText: text => labels.push(text)}, {get: (target, key) => target[key] || (() => {})});
  const make = () => ({textContent: '', dataset: {}, hidden: false, disabled: false, checked: false, handlers: {},
    classList: {toggle() {}, remove() {}}, addEventListener(k, f) {this.handlers[k] = f;},
    querySelector: () => ({value: 'csrf'}), getContext: () => ctx,
    readyState: 4, videoWidth: 1280, videoHeight: 720, play: async () => {},
    toBlob: fn => fn(new Blob(['synthetic-image'], {type: 'image/jpeg'}))});
  const root = make(); root.dataset = {browserContext: 'session', browserContextUrl: '/context/',
    stateUrl: '/state/', heartbeatUrl: '/heartbeat/', detectionUrl: '/detection/',
    weaponEnabled: 'true', weaponUrl: '/weapon/', weaponAcademicDemo: academicDemo ? 'true' : 'false'};
  let ready, finish, sent, legacy = 0, uploads = 0, opens = 0;
  const sentPromise = new Promise(resolve => {sent = resolve;});
  const pending = new Promise(resolve => {finish = resolve;});
  let permissionResolve, permissionRequested, released = 0;
  const permissionReady = new Promise(resolve => {permissionRequested = resolve;});
  const response = body => ({ok: true, status: 200, headers: {get: name => name === 'Content-Type' ? 'application/json' : null}, json: async () => body});
  const window = {crypto, isSecureContext: true, location: {origin: 'https://example.test'},
    addEventListener: (k, fn) => {events[k] = fn;},
    SentinelleBrowserCameraStore: {read: async () => ({cameraId: 'own'})},
    ort: {InferenceSession: {}}, YoloDetector: {create: async () => ({detect: async () => []})}};
  const context = vm.createContext({window, crypto, URL, Headers, Blob, FormData, TextEncoder, Date,
    atob, performance, console,
    document: {addEventListener: (_, fn) => {ready = fn;}, createElement: make,
      getElementById: id => id === 'camera-monitor' ? root : (nodes[id] ||= make())},
    navigator: {mediaDevices: {getUserMedia: async () => {
      opens++;
      if (failPermission) {const error = new Error('refused'); error.name = 'NotAllowedError'; throw error;}
      const stream = {getTracks: () => [{stop() {released++;}}]};
      if (stopDuringPermission) {
        const permission = new Promise(resolve => {permissionResolve = () => resolve(stream);});
        permissionRequested(); return permission;
      }
      return stream;
    }}},
    setInterval: () => 1, clearInterval() {}, setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout() {},
    fetch: async (url, options) => {
      if (String(url).includes('camera=own')) return response({access_token: 'fixture', event_signing_key: 'key'});
      if (url === '/context/') return response({camera_ids: ['own']});
      if (url === '/weapon/') {uploads++; sent(options); return pending;}
      if (url === '/detection/') legacy++;
      return response({name: 'Fixture', monitoring_active: monitoringActive, analysis: {presence_seconds: 1}});
    }});
  for (const name of ['detection-policy.js', 'temporal-tracker.js', 'detection-rules.js', 'event-contract-v2.js', 'weapon-review.js', 'camera-monitor.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8'), context);
  }
  window.SentinelleEventV2 = context.SentinelleEventV2;
  await ready();
  assert.equal(uploads, 0); assert.equal(opens, 0);
  if (useExistingCamera) {
    await nodes['start-camera'].handlers.click();
    await timers.shift()(); // no opt-in: no weapon request
  }
  const starting = nodes['start-weapon-test'].handlers.click();
  if (stopDuringPermission) {
    await permissionReady;
    nodes['stop-weapon-test'].handlers.click();
    permissionResolve(); await starting;
    return {nodes, uploads, opens, released};
  }
  await starting;
  if (failPermission) return {nodes, uploads, opens};
  if (!monitoringActive) return {nodes, uploads, released: () => released};
  await timers.shift()();
  const request = await Promise.race([sentPromise, new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error('No signed weapon request')), 1500); timer.unref();
  })]);
  return {nodes, events, labels, request, legacy: () => legacy, finish: async () => {
    finish(response({state: 'suspected', mode: 'review', ...(academicDemo ? {
      academic_demo: true, event_id: 'demo', detail_url: demoUrl} : {}), detections: [
      {label: 'knife', confidence: .9, bbox: [.1, .2, .3, .4]}]}));
    await new Promise(resolve => setImmediate(resolve));
  }};
}

test('real monitor sends a signed observation without a person and shows a tentative box', async () => {
  const app = await monitor();
  assert.equal(app.request.body.get('model_name'), 'weapon-observation');
  assert.equal(JSON.parse(app.request.body.get('objects'))[0].label, 'scene');
  assert.match(app.request.headers.get('X-Camera-Signature'), /^[a-f0-9]{64}$/);
  await app.finish();
  assert.equal(app.nodes['weapon-result'].textContent, 'Suspicion d’arme');
  assert.ok(app.labels.includes('Couteau ?'));
  assert.equal(app.legacy(), 0);
});

test('stopping real monitor rejects a late weapon result and clears the opt-in', async () => {
  const app = await monitor(); app.nodes['stop-weapon-test'].handlers.click(); await app.finish();
  assert.equal(app.nodes['weapon-review-toggle'].checked, false);
  assert.equal(app.nodes['weapon-result'].textContent, 'Arrêté');
  assert.ok(!app.labels.includes('Couteau ?'));
});

test('start test also works with an already open webcam', async () => {
  const app = await monitor({useExistingCamera: true});
  assert.equal(app.nodes['weapon-review-toggle'].checked, true);
  assert.match(app.request.headers.get('X-Camera-Signature'), /^[a-f0-9]{64}$/);
  await app.finish();
  assert.equal(app.nodes['weapon-result'].textContent, 'Suspicion d’arme');
});

test('stop cancels a pending start and releases a webcam permission granted later', async () => {
  const app = await monitor({stopDuringPermission: true});
  assert.equal(app.uploads, 0); assert.equal(app.released, 1);
  assert.equal(app.nodes['weapon-result'].textContent, 'Arrêté');
  assert.equal(app.nodes['start-weapon-test'].disabled, false);
});

test('permission refusal is visible next to the test button and permits retry', async () => {
  const app = await monitor({failPermission: true});
  assert.equal(app.uploads, 0);
  assert.equal(app.nodes['weapon-result'].dataset.state, 'camera_error');
  assert.match(app.nodes['weapon-help'].textContent, /Autorisez la webcam/);
  assert.equal(app.nodes['start-weapon-test'].disabled, false);
});

test('test stop remains available when surveillance is paused', async () => {
  const app = await monitor({monitoringActive: false});
  assert.equal(app.uploads, 0);
  assert.equal(app.nodes['weapon-result'].dataset.state, 'paused');
  assert.equal(app.nodes['stop-weapon-test'].disabled, false);
  app.nodes['stop-weapon-test'].handlers.click();
  assert.equal(app.released(), 1);
  assert.equal(app.nodes['weapon-result'].textContent, 'Arrêté');
});

test('single start button signs academic choice on the isolated demo and shows the local event notice', async () => {
  const app = await monitor({academicDemo: true});
  assert.equal(app.request.body.get('model_name'), 'weapon-observation-academic-demo');
  assert.match(app.request.headers.get('X-Camera-Signature'), /^[a-f0-9]{64}$/);
  await app.finish();
  assert.equal(app.nodes['weapon-demo-notice'].hidden, false);
  assert.equal(app.nodes['weapon-demo-link'].href, '/demo-event/');
  app.events['sentinelle:account-changed']();
  assert.equal(app.nodes['weapon-demo-notice'].hidden, true);
  assert.equal(app.nodes['weapon-demo-link'].href, '#');
});

test('academic event link refuses an external URL', async () => {
  const app = await monitor({academicDemo: true, demoUrl: '//example.test/foreign'});
  await app.finish();
  assert.equal(app.nodes['weapon-demo-notice'].hidden, true);
});
