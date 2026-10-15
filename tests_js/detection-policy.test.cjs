const assert = require("node:assert/strict");
const test = require("node:test");

require("../static/js/detection-policy.js");

const policy = globalThis.SentinelleDetectionPolicy;

test("retient seulement les classes configurées au-dessus de leur seuil", () => {
  const accepted = policy.acceptedPredictions([
    {class: "person", score: 0.45, bbox: [0, 0, 10, 10]},
    {class: "dog", score: 0.49, bbox: [20, 0, 10, 10]},
    {class: "cat", score: 0.80, bbox: [40, 0, 10, 10]},
    {class: "car", score: 0.99, bbox: [60, 0, 10, 10]}
  ]);

  assert.deepEqual(accepted.map(item => item.class), ["person", "cat"]);
});

test("supprime les doublons uniquement à l’intérieur de la même classe", () => {
  const kept = policy.suppressDuplicates([
    {class: "person", score: 0.90, bbox: [0, 0, 100, 100]},
    {class: "person", score: 0.80, bbox: [2, 2, 100, 100]},
    {class: "dog", score: 0.70, bbox: [2, 2, 100, 100]}
  ]);

  assert.deepEqual(kept.map(item => item.class), ["person", "dog"]);
});

test("applique les seuils reçus de la caméra", () => {
  const accepted = policy.acceptedPredictions([
    {class: "person", score: 0.60, bbox: [0, 0, 10, 10]},
    {class: "dog", score: 0.69, bbox: [20, 0, 10, 10]},
    {class: "cat", score: 0.70, bbox: [40, 0, 10, 10]}
  ], {person: 0.65, dog: 0.70, cat: 0.70});

  assert.deepEqual(accepted.map(item => item.class), ["cat"]);
});
