const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = name => fs.readFileSync(path.join(__dirname, '../static/js/', name), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function storage(initial) {
  const rows = new Map(initial.map(row => [row.cameraId, row]));
  const indexedDB = {open() {
    const request = {};
    queueMicrotask(() => {
      request.result = {objectStoreNames: {contains: () => true}, close() {}, transaction() {
        const tx = {objectStore() {return {
          getAll() {
            const read = {};
            queueMicrotask(() => {read.result = [...rows.values()]; read.onsuccess(); queueMicrotask(() => tx.oncomplete());});
            return read;
          },
          put(value) {rows.set(value.cameraId, plain(value));},
        };}};
        return tx;
      }};
      request.onsuccess();
    });
    return request;
  }};
  const window = {};
  vm.runInNewContext(script('browser-camera-store.js'), {window, indexedDB});
  return {api: window.SentinelleBrowserCameraStore, rows};
}

test('legacy secrets are scrubbed and the most recent foreign camera is never selected', async () => {
  const app = storage([
    {cameraId: 'a', pairedAt: 100, deviceSecret: 'old-secret', accessToken: 'old-token', eventSigningKey: 'old-signing-key'},
    {cameraId: 'b', pairedAt: 1, deviceId: 'old-id'},
  ]);
  assert.deepEqual(plain(await app.api.read(['b'])), {cameraId: 'b', pairedAt: 1, pairingVersion: 1});
  assert.deepEqual([...app.rows.values()], [{cameraId: 'a', pairedAt: 100, pairingVersion: 1}, {cameraId: 'b', pairedAt: 1, pairingVersion: 1}]);
});

test('a forbidden requested camera cannot fall back to another camera', async () => {
  const app = storage([{cameraId: 'a', pairedAt: 10}, {cameraId: 'b', pairedAt: 1}]);
  assert.equal(await app.api.read(['b'], 'a'), null);
  assert.equal(await app.api.read([]), null);
});

test('pairing generation survives reads without upgrading a legacy record', async () => {
  const app = storage([{cameraId: 'new', pairedAt: 20, pairingVersion: 3}, {cameraId: 'old', pairedAt: 10}]);
  assert.equal((await app.api.read(['new'])).pairingVersion, 3);
  assert.equal((await app.api.read(['old'])).pairingVersion, 1);
});

test('successful pairing persists its generation without device secrets', async () => {
  let saved;
  const status = {textContent: '', classList: {add() {}}};
  vm.runInNewContext(script('pair-camera.js'), {
    document: {getElementById: id => id === 'camera-credentials' ? {textContent: JSON.stringify({cameraId: 'new', pairingVersion: 4})} : status},
    window: {SentinelleBrowserCameraStore: {save: async value => {saved = value;}}}, Date,
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(saved.pairingVersion, 4);
  assert.equal(saved.cameraId, 'new');
  assert.deepEqual(Object.keys(saved).sort(), ['cameraId', 'pairedAt', 'pairingVersion']);
  assert.match(status.textContent, /webcam reste éteinte/);
});

test('logout and other-tab account changes notify an active monitor', () => {
  const handlers = {}, events = [], sent = [];
  let channel;
  class Channel {constructor() {channel = this;} postMessage(value) {sent.push(value);}}
  const window = {addEventListener: (key, fn) => {handlers[key] = fn;}, dispatchEvent: event => events.push(event.type)};
  vm.runInNewContext(script('browser-camera-session.js'), {window, document: {body: {dataset: {cameraSessionContext: 'session-a'}}},
    BroadcastChannel: Channel, localStorage: {setItem() {}}, Event});
  assert.deepEqual(sent, ['session-a']);
  channel.onmessage({data: 'session-a'}); assert.equal(events.length, 0);
  channel.onmessage({data: ''}); channel.onmessage({data: 'session-b'});
  handlers.storage({key: 'sentinelle-camera-session', newValue: 'session-b'});
  assert.deepEqual(events, ['sentinelle:account-changed', 'sentinelle:account-changed', 'sentinelle:account-changed']);
});

function monitor({authorized = true, pairingVersion = 1, serverGeneration = pairingVersion} = {}) {
  const nodes = {}, events = {};
  const make = () => ({textContent: '', hidden: false, disabled: false, handlers: {},
    classList: {toggle() {}, remove() {}}, addEventListener(key, fn) {this.handlers[key] = fn;},
    querySelector: () => ({value: 'csrf-token'}), getContext: () => ({clearRect() {}})});
  const root = make(); root.dataset = {browserContext: 'a', browserContextUrl: '/context/', stateUrl: '/state/', requestedCameraId: ''};
  let ready, webcamCalls = 0, stopped = 0, resolveCamera;
  const requests = [];
  const document = {addEventListener: (_, fn) => {ready = fn;}, getElementById: id => id === 'camera-monitor' ? root : (nodes[id] ||= make())};
  const window = {isSecureContext: true, location: {origin: 'https://example.test'},
    addEventListener: (key, fn) => {events[key] = fn;}, SentinelleTemporalTracker: class {reset() {}},
    SentinelleBrowserCameraStore: {read: async ids => ids.includes('own') ? {cameraId: 'own', pairingVersion} : null}};
  const response = (payload, status = 200) => ({ok: status === 200, status, headers: {get: name => name === 'Content-Type' ? 'application/json' : null}, json: async () => payload});
  vm.runInNewContext(script('camera-monitor.js'), {window, document, URL, Headers, Date, console,
    navigator: {mediaDevices: {getUserMedia: () => {webcamCalls++; return new Promise(resolve => {resolveCamera = resolve;});}}},
    fetch: async (url, options) => {
      requests.push(String(url));
      if (String(url).includes('camera=own')) {
        if (new URL(url).searchParams.get('pairing_version') !== String(serverGeneration)) return response({detail: 'Old pairing replaced'}, 409);
        return response({access_token: 'fixture-token', event_signing_key: 'fixture-key'});
      }
      if (String(url).includes('/context/')) return response({camera_ids: authorized ? ['own'] : []});
      return response({name: 'Own camera', monitoring_active: true, analysis: {}});
    }, setInterval: () => 1, clearInterval() {}, clearTimeout() {}, setTimeout});
  return {nodes, events, requests, ready: () => ready(), webcamCalls: () => webcamCalls, stopped: () => stopped,
    resolve: () => resolveCamera({getTracks: () => [{stop() {stopped++;}}]}),
    start: () => nodes['start-camera'].handlers.click()};
}

test('an account with no allowed camera never requests a foreign state or opens the webcam', async () => {
  const app = monitor({authorized: false}); await app.ready();
  assert.equal(app.webcamCalls(), 0);
  assert.deepEqual(app.requests, ['/context/']);
  assert.equal(app.nodes['start-camera'].disabled, true);
  assert.match(app.nodes['camera-status'].textContent, /Aucune caméra.*compte/);
});

test('a replaced browser pairing cannot renew or start the camera', async () => {
  const app = monitor({pairingVersion: 1, serverGeneration: 2}); await app.ready();
  assert.equal(app.webcamCalls(), 0);
  assert.equal(app.nodes['start-camera'].disabled, true);
  assert.match(app.nodes['camera-status'].textContent, /Appairez de nouveau/);
  assert.equal(app.requests.some(url => url === '/state/'), false);
});

test('new pairing sends its generation and can read camera state with webcam off', async () => {
  const app = monitor({pairingVersion: 2}); await app.ready();
  assert.equal(app.nodes['start-camera'].disabled, false);
  assert.equal(app.webcamCalls(), 0);
  assert.ok(app.requests.some(url => url.includes('pairing_version=2')));
});

test('account change clears camera metadata and blocks a new camera start', async () => {
  const app = monitor(); await app.ready();
  assert.equal(app.nodes['camera-title'].textContent, 'Own camera');
  app.events['sentinelle:account-changed']();
  await app.start();
  assert.equal(app.nodes['camera-title'].textContent, 'Mode caméra');
  assert.equal(app.nodes['start-camera'].disabled, true); assert.equal(app.webcamCalls(), 0);
});

test('late camera permission after an account change immediately closes the stream', async () => {
  const app = monitor(); await app.ready();
  const starting = app.start();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.webcamCalls(), 1);
  app.events['sentinelle:account-changed'](); app.resolve(); await starting;
  assert.equal(app.stopped(), 1);
  assert.equal(app.nodes['start-camera'].disabled, true);
});
