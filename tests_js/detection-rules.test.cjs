const assert = require("node:assert/strict");
const test = require("node:test");

require("../static/js/detection-rules.js");

const zone = {x: 0.1, y: 0.1, width: 0.8, height: 0.8};
const line = {x1: 0.5, y1: 0, x2: 0.5, y2: 1};
const config = {zone, line, presenceSeconds: 2, forbiddenCrossingDirection: "negative_to_positive"};
const tracked = overrides => ({
  class: "person", score: 0.9, bbox: [0.4, 0.2, 0.2, 0.5], trackId: "track-1",
  trackDurationSeconds: 1.5, zoneDurationSeconds: 1.5, insideZone: true,
  crossingDirection: null, ...overrides
});

test("ignore un franchissement dans le sens autorisé", () => {
  const result = globalThis.SentinelleRuleEvaluator.evaluate([
    tracked({crossingDirection: "positive_to_negative"})
  ], config);

  assert.equal(result, null);
});

test("explique le franchissement dans le sens interdit", () => {
  const result = globalThis.SentinelleRuleEvaluator.evaluate([
    tracked({crossingDirection: "negative_to_positive"})
  ], config);

  assert.equal(result.context.id, "line-crossing");
  assert.equal(result.context.direction, "negative_to_positive");
  assert.deepEqual(result.context.zone, zone);
});

test("conserve une personne et un animal suivis dans une présence prolongée", () => {
  const result = globalThis.SentinelleRuleEvaluator.evaluate([
    tracked({zoneDurationSeconds: 2.2}),
    tracked({class: "dog", trackId: "track-2", zoneDurationSeconds: 2.1})
  ], config);

  assert.deepEqual(result.predictions.map(item => item.class), ["person", "dog"]);
  assert.deepEqual(result.context.track_ids, ["track-1", "track-2"]);
});
