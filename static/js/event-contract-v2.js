(() => {
  "use strict";

  const fixed = value => Number(value).toFixed(6);

  const canonicalObjects = objects => {
    const normalized = objects.map(item => ({
      bbox: item.bbox.map(fixed),
      confidence: fixed(item.confidence),
      label: item.label,
      track_id: item.track_id || ""
    }));
    normalized.sort((left, right) => {
      const leftKey = `${left.label}\u0000${left.track_id}\u0000${left.bbox.join(",")}\u0000${left.confidence}`;
      const rightKey = `${right.label}\u0000${right.track_id}\u0000${right.bbox.join(",")}\u0000${right.confidence}`;
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
    });
    return JSON.stringify(normalized);
  };

  const canonicalObservedAt = value => new Date(value).toISOString();

  const canonicalRuleContext = rule => {
    if (!rule) return "";
    const line = rule.line;
    return JSON.stringify({
      duration_seconds: fixed(rule.duration_seconds),
      direction: rule.direction || null,
      id: rule.id,
      line: line ? {x1: fixed(line.x1), y1: fixed(line.y1), x2: fixed(line.x2), y2: fixed(line.y2)} : null,
      track_ids: [...rule.track_ids].sort(),
      type: rule.type,
      version: Number(rule.version),
      zone: {
        x: fixed(rule.zone.x), y: fixed(rule.zone.y),
        width: fixed(rule.zone.width), height: fixed(rule.zone.height)
      }
    });
  };

  const signaturePayload = ({
    method, path, cameraId, timestamp, nonce, eventId, observedAt,
    modelName, modelVersion, objects, simulated, captureType, captureDigest, ruleContext
  }) => {
    const parts = [
    "sentinelle-event-v2",
    method.toUpperCase(),
    path,
    String(cameraId),
    String(timestamp),
    String(nonce),
    String(eventId),
    canonicalObservedAt(observedAt),
    modelName,
    modelVersion,
    canonicalObjects(objects),
    simulated ? "1" : "0",
    captureType.toLowerCase(),
    captureDigest.toLowerCase()
    ];
    if (ruleContext) parts.push("sentinelle-rule-context-v1", canonicalRuleContext(ruleContext));
    return parts.join("\n");
  };

  globalThis.SentinelleEventV2 = {canonicalObjects, canonicalObservedAt, canonicalRuleContext, signaturePayload};
})();
