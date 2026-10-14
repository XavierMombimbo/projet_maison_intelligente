const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const test = require("node:test");

require("../static/js/event-contract-v2.js");

const ruleContext = {
  id: "line-crossing",
  version: 1,
  type: "line_crossing",
  duration_seconds: 1.25,
  zone: {x: 0.1, y: 0.2, width: 0.7, height: 0.6},
  line: {x1: 0.5, y1: 0, x2: 0.5, y2: 1},
  direction: "negative_to_positive",
  track_ids: ["track-2", "track-1"]
};

test("canonise le contexte de règle de façon déterministe", () => {
  assert.equal(
    globalThis.SentinelleEventV2.canonicalRuleContext(ruleContext),
    '{"duration_seconds":"1.250000","direction":"negative_to_positive","id":"line-crossing","line":{"x1":"0.500000","y1":"0.000000","x2":"0.500000","y2":"1.000000"},"track_ids":["track-1","track-2"],"type":"line_crossing","version":1,"zone":{"x":"0.100000","y":"0.200000","width":"0.700000","height":"0.600000"}}'
  );
});

test("inclut le contexte de règle dans la signature", () => {
  const payload = globalThis.SentinelleEventV2.signaturePayload({
    method: "POST",
    path: "/api/camera/me/detections/",
    cameraId: "11111111-1111-4111-8111-111111111111",
    timestamp: 1790150400,
    nonce: "22222222-2222-4222-8222-222222222222",
    eventId: "33333333-3333-4333-8333-333333333333",
    observedAt: "2026-09-23T08:00:00.123Z",
    modelName: "yolo11n",
    modelVersion: "320@test",
    objects: [{label: "person", confidence: 0.9, bbox: [0.1, 0.2, 0.3, 0.4], track_id: "track-1"}],
    simulated: false,
    captureType: "image/jpeg",
    captureDigest: "a".repeat(64),
    ruleContext
  });
  const signature = crypto.createHmac("sha256", "vector-key-2026").update(payload).digest("hex");

  assert.equal(signature, "e650616b10356be84a7b1c84bd94a2afc7351706ca6100964d539be63c6ab50c");
});
