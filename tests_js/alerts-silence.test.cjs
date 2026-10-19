const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function runtime() {
  let onMessage;
  const effects = {toasts: 0, sounds: 0};
  const nodes = {
    'global-alert-runtime': {dataset: {wsPath: '/ws/alerts/'}},
    'alert-toasts': {prepend() { effects.toasts++; }},
    'new-alert-count': {textContent: '0'},
  };
  function element() {
    return {classList: {add() {}}, setAttribute() {}, addEventListener() {}, append() {}, remove() {}};
  }
  const audioParam = {setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {}};
  class AudioContext {
    currentTime = 0;
    createOscillator() { effects.sounds++; return {frequency: audioParam, connect() { return {connect() {}}; }, start() {}, stop() {}, disconnect() {}, addEventListener() {}}; }
    createGain() { return {gain: audioParam}; }
  }
  class WebSocket {
    addEventListener(type, callback) { if (type === 'message') onMessage = callback; }
  }
  const window = {location: {protocol: 'https:', host: 'fixture.test'}, AudioContext,
    setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/alerts.js'), 'utf8'), {
    window, WebSocket, localStorage: {getItem() { return 'on'; }},
    document: {getElementById(id) { return nodes[id]; }, querySelectorAll() { return []; }, createElement: element},
  });
  return {effects, count: nodes['new-alert-count'], send(payload) { onMessage({data: JSON.stringify(payload)}); }};
}

test('silent presence produces no toast, siren or alert count', () => {
  const app = runtime();
  app.send({type: 'alert.created', event_id: 'known', notification_suppressed: true});
  assert.deepEqual(app.effects, {toasts: 0, sounds: 0});
  assert.equal(app.count.textContent, '0');
});

test('notifiable and legacy alerts still ring once; duplicate delivery stays silent', () => {
  const app = runtime();
  for (const payload of [
    {type: 'alert.created', event_id: 'crossing', alert_priority: 100, notification_suppressed: false},
    {type: 'alert.created', event_id: 'legacy'},
  ]) { app.send(payload); app.send(payload); }
  assert.deepEqual(app.effects, {toasts: 2, sounds: 2});
  assert.equal(app.count.textContent, '2');
});
