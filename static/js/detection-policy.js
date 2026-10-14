(() => {
  "use strict";

  const CLASSES = Object.freeze({
    person: Object.freeze({cocoIndex: 0, threshold: 0.45, label: "Personne", color: "#26e39a"}),
    dog: Object.freeze({cocoIndex: 16, threshold: 0.50, label: "Chien", color: "#f59e0b"}),
    cat: Object.freeze({cocoIndex: 15, threshold: 0.50, label: "Chat", color: "#60a5fa"})
  });

  const intersectionOverUnion = (left, right) => {
    const x1 = Math.max(left[0], right[0]);
    const y1 = Math.max(left[1], right[1]);
    const x2 = Math.min(left[0] + left[2], right[0] + right[2]);
    const y2 = Math.min(left[1] + left[3], right[1] + right[3]);
    const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
    return intersection / (left[2] * left[3] + right[2] * right[3] - intersection || 1);
  };

  const acceptedPredictions = (predictions, thresholds = {}) => predictions.filter(item => {
    const settings = CLASSES[item.class];
    const threshold = Number.isFinite(Number(thresholds[item.class]))
      ? Number(thresholds[item.class])
      : settings?.threshold;
    return Boolean(settings) && Number.isFinite(item.score) && item.score >= threshold;
  });

  const suppressDuplicates = (predictions, iouThreshold = 0.45, limit = 64, thresholds = {}) => {
    const ordered = acceptedPredictions(predictions, thresholds).sort((left, right) => right.score - left.score);
    const kept = [];
    for (const candidate of ordered) {
      const duplicate = kept.some(item => (
        item.class === candidate.class
        && intersectionOverUnion(item.bbox, candidate.bbox) > iouThreshold
      ));
      if (!duplicate) kept.push(candidate);
      if (kept.length >= limit) break;
    }
    return kept;
  };

  const scope = typeof window === "undefined" ? globalThis : window;
  scope.SentinelleDetectionPolicy = Object.freeze({
    classes: CLASSES,
    acceptedPredictions,
    suppressDuplicates
  });
})();
