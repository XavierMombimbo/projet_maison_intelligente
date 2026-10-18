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
  assert.deepEqual(plain(await app.api.read(['b'])), {cameraId: 'b', pairedAt: 1});
  assert.deepEqual([...app.rows.values()], [{cameraId: 'a', pairedAt: 100}, {cameraId: 'b', pairedAt: 1}]);
});

test('a forbidden requested camera cannot fall back to another camera', async () => {
  const app = storage([{cameraId: 'a', pairedAt: 10}, {cameraId: 'b', pairedAt: 1}]);
  assert.equal(await app.api.read(['b'], 'a'), null);
  assert.equal(await app.api.read([]), null);
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

function monitor({authorized = true} = {}) {
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
    SentinelleBrowserCameraStore: {read: async ids => ids.includes('own') ? {cameraId: 'own'} : null}};
  const response = payload => ({ok: true, status: 200, headers: {get: name => name === 'Content-Type' ? 'application/json' : null}, json: async () => payload});
  vm.runInNewContext(script('camera-monitor.js'), {window, document, URL, Headers, Date, console,
    navigator: {mediaDevices: {getUserMedia: () => {webcamCalls++; return new Promise(resolve => {resolveCamera = resolve;});}}},
    fetch: async (url, options) => {
      requests.push(String(url));
      if (String(url).includes('camera=own')) return response({access_token: 'fixture-token', event_signing_key: 'fixture-key'});
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
