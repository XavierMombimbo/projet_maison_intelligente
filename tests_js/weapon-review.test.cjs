const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function fixture(send) {
  const context = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/weapon-review.js'), 'utf8'), context);
  let time = 0, id = 0, messages = [];
  const api = context.SentinelleWeaponReview.create({send, render: text => messages.push(text), now: () => time, newId: () => String(++id)});
  return {api, messages, advance: () => {time += 1600;}};
}
test('no upload before opt in or while camera is inactive', async () => {
  let calls = 0; const f = fixture(async () => {calls++; return {state: 'clear'};});
  await f.api.sample(async () => 'frame', () => true);
  f.api.start(); await f.api.sample(async () => 'frame', () => false);
  assert.equal(calls, 0);
});
test('stopping ignores a late suspicion result and a restart changes run', async () => {
  let finish, firstRun;
  const f = fixture((blob, id, run) => {firstRun = run; return new Promise(resolve => {finish = resolve;});});
  f.api.start(); const pending = f.api.sample(async () => 'frame', () => true);
  await new Promise(resolve => setImmediate(resolve));
  f.api.stop(); finish({state: 'suspected', mode: 'review'}); await pending;
  assert.equal(f.messages.at(-1), 'Arrêté');
  f.api.start(); assert.ok(firstRun);
});
test('capture completing after stop is never transmitted', async () => {
  let release, calls = 0; const f = fixture(async () => {calls++;});
  f.api.start(); const pending = f.api.sample(() => new Promise(resolve => {release = resolve;}), () => true);
  f.api.stop(); release('frame'); await pending; assert.equal(calls, 0);
});
test('single request at a time and interval limit', async () => {
  let calls = 0; const f = fixture(async () => {calls++; return {state: 'clear'};});
  f.api.start(); await Promise.all([f.api.sample(async () => 'frame', () => true), f.api.sample(async () => 'frame', () => true)]);
  await f.api.sample(async () => 'frame', () => true); assert.equal(calls, 1);
  f.advance(); await f.api.sample(async () => 'frame', () => true); assert.equal(calls, 2);
});
test('failure stays distinct from clear and remains isolated', async () => {
  const f = fixture(async () => {throw new Error('offline');}); f.api.start();
  await f.api.sample(async () => 'frame', () => true);
  assert.equal(f.messages.at(-1), 'Analyse indisponible');
});
