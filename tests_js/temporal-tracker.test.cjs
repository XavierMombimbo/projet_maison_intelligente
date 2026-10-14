const assert = require("node:assert/strict");
const test = require("node:test");

require("../static/js/temporal-tracker.js");

const detection = (x = 0.2) => ({class: "person", score: 0.9, bbox: [x, 0.2, 0.2, 0.4]});
const zone = {x: 0.1, y: 0.1, width: 0.7, height: 0.8};

const durationAfterOneSecond = (timestamps) => {
  const tracker = new globalThis.SentinelleTemporalTracker();
  let result;
  for (const timestamp of timestamps) result = tracker.update([detection()], timestamp, zone)[0];
  return result.zoneDurationSeconds;
};

test("mesure la présence en secondes quelle que soit la cadence", () => {
  assert.equal(durationAfterOneSecond([0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]), 1);
  assert.equal(durationAfterOneSecond([0, 500, 1000]), 1);
});

test("sépare les pistes par classe et conserve un identifiant stable", () => {
  const tracker = new globalThis.SentinelleTemporalTracker();
  const first = tracker.update([detection(), {...detection(), class: "dog"}], 0, zone);
  const second = tracker.update([detection(0.21), {...detection(0.21), class: "dog"}], 400, zone);

  assert.equal(second[0].trackId, first[0].trackId);
  assert.equal(second[1].trackId, first[1].trackId);
  assert.notEqual(second[0].trackId, second[1].trackId);
});

test("réinitialise la durée hors zone et après une longue interruption", () => {
  const tracker = new globalThis.SentinelleTemporalTracker({maxMissingMs: 500});
  tracker.update([detection()], 0, zone);
  const inside = tracker.update([detection()], 400, zone)[0];
  const outside = tracker.update([detection(0.85)], 500, zone)[0];
  const afterGap = tracker.update([detection()], 1200, zone)[0];

  assert.equal(inside.zoneDurationSeconds, 0.4);
  assert.equal(outside.zoneDurationSeconds, 0);
  assert.notEqual(afterGap.trackId, inside.trackId);
});

test("refuse une zone normalisée qui dépasse l’image", () => {
  const geometry = globalThis.SentinelleTrackingGeometry;

  assert.equal(geometry.validZone(zone), true);
  assert.equal(geometry.validZone({x: 0.8, y: 0, width: 0.3, height: 1}), false);
});

test("détecte la direction d’un franchissement de ligne", () => {
  const tracker = new globalThis.SentinelleTemporalTracker();
  const vertical = {x1: 0.5, y1: 0, x2: 0.5, y2: 1};
  tracker.update([detection(0.25)], 0, zone, vertical);
  const crossed = tracker.update([detection(0.41)], 300, zone, vertical)[0];

  assert.equal(crossed.crossingDirection, "negative_to_positive");
});

test("conserve la piste pendant un franchissement rapide entre deux analyses", () => {
  const tracker = new globalThis.SentinelleTemporalTracker();
  const vertical = {x1: 0.5, y1: 0, x2: 0.5, y2: 1};
  const before = tracker.update([detection(0.20)], 0, zone, vertical)[0];
  const crossed = tracker.update([detection(0.55)], 700, zone, vertical)[0];

  assert.equal(crossed.trackId, before.trackId);
  assert.equal(crossed.crossingDirection, "negative_to_positive");
});
