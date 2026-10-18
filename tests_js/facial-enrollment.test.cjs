const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(require('node:path').join(__dirname, '../static/js/facial-enrollment.js'), 'utf8');

function setup({pending = false, response = {ok: true, status: 'enrolled'}} = {}) {
  const listeners = new Map();
  const element = () => ({hidden: false, disabled: false, checked: false, textContent: '',
    handlers: {}, addEventListener(name, fn) {this.handlers[name] = fn;}, focus() {this.focused = true;}});
  const nodes = {};
  for (const name of ['form', 'video', 'preview', 'consent', 'start', 'save', 'cancel', 'status', 'success']) nodes[name] = element();
  nodes.video.videoWidth = 640; nodes.video.videoHeight = 480; nodes.video.play = async () => {};
  nodes.form.querySelector = () => ({value: 'csrf-fixture'});
  const heading = element();
  const root = {dataset: {submitUrl: '/own-profile/enroler/'},
    querySelector: selector => selector === 'h1' ? heading : nodes[selector.match(/data-face-(.*)\]/)[1]],
    setAttribute() {}, removeAttribute() {}};
  let opened = 0, stopped = 0, resolveMedia;
  const requests = [];
  const track = {stop() {stopped++;}};
  const stream = {getTracks: () => [track]};
  const canvas = {width: 0, height: 0, getContext: () => ({drawImage() {}}), toDataURL: () => 'data:image/jpeg;base64,c3ludGhldGlj'};
  const document = {hidden: false, querySelector: () => root, createElement: () => canvas,
    addEventListener: (name, fn) => listeners.set(name, fn)};
  vm.runInNewContext(code, {document, window: {addEventListener: (name, fn) => listeners.set(name, fn)},
    navigator: {mediaDevices: {getUserMedia: async constraints => {
      opened++; assert.equal(constraints.audio, false);
      return pending ? new Promise(resolve => {resolveMedia = resolve;}) : stream;
    }}}, AbortController, setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options) => {requests.push({url, options}); return {ok: response.ok,
      headers: {get: () => 'application/json'}, json: async () => response};}});
  return {nodes, document, listeners, canvas, requests, heading, stream,
    opened: () => opened, stopped: () => stopped, resolve: () => resolveMedia(stream),
    click: name => nodes[name].handlers.click(), submit: () => nodes.form.handlers.submit({preventDefault() {}})};
}

test('camera and transmission require consent and explicit clicks', async () => {
  const app = setup(); assert.equal(app.opened(), 0);
  await app.click('start'); assert.equal(app.opened(), 0);
  app.nodes.consent.checked = true; await app.click('start');
  assert.equal(app.opened(), 1); assert.equal(app.requests.length, 0);
  await app.click('cancel'); assert.equal(app.stopped(), 1); assert.equal(app.requests.length, 0);
});

test('late camera permission after leaving releases all tracks', async () => {
  const app = setup({pending: true}); app.nodes.consent.checked = true;
  const opening = app.click('start');
  app.listeners.get('pagehide')(); app.resolve(); await opening;
  assert.equal(app.stopped(), 1); assert.equal(app.nodes.video.srcObject, null);
  assert.equal(app.requests.length, 0);
});

test('capture stops camera before sending and clears canvas after success', async () => {
  const app = setup(); app.nodes.consent.checked = true;
  await app.click('start'); await app.submit();
  assert.equal(app.stopped(), 1); assert.equal(app.requests.length, 1);
  const sent = app.requests[0]; assert.equal(sent.options.headers['X-CSRFToken'], 'csrf-fixture');
  assert.equal(sent.options.mode, 'same-origin'); assert.equal(JSON.parse(sent.options.body).consent, true);
  assert.equal(app.nodes.form.hidden, true); assert.equal(app.nodes.success.hidden, false);
  assert.equal(app.canvas.width, 0); assert.equal(app.canvas.height, 0);
});

test('quality failure keeps camera off and offers another explicit attempt', async () => {
  const app = setup({response: {ok: false, detail: 'Un seul visage doit être visible.'}});
  app.nodes.consent.checked = true; await app.click('start'); await app.submit();
  assert.equal(app.stopped(), 1); assert.equal(app.nodes.start.hidden, false);
  assert.equal(app.nodes.start.disabled, false); assert.match(app.nodes.status.textContent, /Un seul visage/);
});

test('withdrawing the checkbox closes the preview without sending', async () => {
  const app = setup(); app.nodes.consent.checked = true; await app.click('start');
  app.nodes.consent.checked = false; app.nodes.consent.handlers.change();
  assert.equal(app.stopped(), 1); assert.equal(app.requests.length, 0);
});
