const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/browser-face-result.js'), 'utf8'), {window});
const describe = window.SentinelleBrowserFaceResult.describe;
test('a known presence distinguishes silence from a maintained crossing alert', () => {
  const face_verification = {state: 'recognized', source: 'server'};
  assert.match(describe({face_verification, notification_sent: false}), /silencieuse/);
  assert.match(describe({face_verification, notification_sent: true}), /alerte maintenue/);
});
test('unknown and unavailable never imply an identity match', () => {
  assert.equal(describe({face_verification: {state: 'unknown', source: 'server'}}), 'Personne non reconnue');
  for (const reason of ['quality', 'busy', 'no_profiles', 'multiple_people', 'service']) {
    assert.doesNotMatch(describe({face_verification: {state: 'unavailable', reason, source: 'server'}}), /Profil reconnu|Personne non reconnue/);
  }
  assert.match(describe({}), /indisponible/);
  assert.match(describe({face_verification: {state: 'recognized', source: 'client'}}), /indisponible/);
});
