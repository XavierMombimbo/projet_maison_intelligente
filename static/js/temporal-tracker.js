(() => {
  "use strict";

  const DEFAULT_ZONE = Object.freeze({x: 0, y: 0, width: 1, height: 1});

  const validZone = (zone) => {
    if (!zone || typeof zone !== "object") return false;
    const values = [zone.x, zone.y, zone.width, zone.height];
    return values.every(Number.isFinite)
      && zone.x >= 0 && zone.y >= 0
      && zone.width > 0 && zone.height > 0
      && zone.x + zone.width <= 1.000001
      && zone.y + zone.height <= 1.000001;
  };

  const intersectionOverUnion = (left, right) => {
    const x1 = Math.max(left[0], right[0]);
    const y1 = Math.max(left[1], right[1]);
    const x2 = Math.min(left[0] + left[2], right[0] + right[2]);
    const y2 = Math.min(left[1] + left[3], right[1] + right[3]);
    const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
    return intersection / (left[2] * left[3] + right[2] * right[3] - intersection || 1);
  };

  const center = (bbox) => [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2];
  const centerDistance = (left, right) => {
    const [leftX, leftY] = center(left);
    const [rightX, rightY] = center(right);
    return Math.hypot(leftX - rightX, leftY - rightY);
  };
  const insideZone = (bbox, zone) => {
    const [x, y] = center(bbox);
    return x >= zone.x && x <= zone.x + zone.width && y >= zone.y && y <= zone.y + zone.height;
  };
  const lineSide = (bbox, line) => {
    const [x, y] = center(bbox);
    return (x - line.x1) * (line.y2 - line.y1) - (y - line.y1) * (line.x2 - line.x1);
  };

  class TemporalTracker {
    constructor({maxMissingMs = 1200, minimumIou = 0.10, maximumCenterDistance = 0.45} = {}) {
      this.maxMissingMs = maxMissingMs;
      this.minimumIou = minimumIou;
      this.maximumCenterDistance = maximumCenterDistance;
      this.sequence = 0;
      this.tracks = new Map();
    }

    reset() {
      this.tracks.clear();
      this.sequence = 0;
    }

    update(detections, timestampMs, requestedZone = DEFAULT_ZONE, line = null) {
      const now = Number(timestampMs);
      if (!Number.isFinite(now)) throw new Error("L’horodatage du suivi est invalide.");
      const zone = validZone(requestedZone) ? requestedZone : DEFAULT_ZONE;
      for (const [trackId, track] of this.tracks) {
        if (now - track.lastSeenMs > this.maxMissingMs) this.tracks.delete(trackId);
      }

      const availableTrackIds = new Set(this.tracks.keys());
      return detections.map(detection => {
        let bestTrack = null;
        let bestScore = -Infinity;
        for (const trackId of availableTrackIds) {
          const track = this.tracks.get(trackId);
          if (track.class !== detection.class) continue;
          const overlap = intersectionOverUnion(track.bbox, detection.bbox);
          const distance = centerDistance(track.bbox, detection.bbox);
          if (overlap < this.minimumIou && distance > this.maximumCenterDistance) continue;
          const score = overlap - distance;
          if (score > bestScore) {
            bestScore = score;
            bestTrack = track;
          }
        }

        const isInside = insideZone(detection.bbox, zone);
        const currentLineSide = line ? lineSide(detection.bbox, line) : null;
        let crossingDirection = null;
        if (!bestTrack) {
          const trackId = `track-${++this.sequence}`;
          bestTrack = {
            id: trackId,
            class: detection.class,
            bbox: detection.bbox,
            firstSeenMs: now,
            lastSeenMs: now,
            inside: isInside,
            insideDurationMs: 0,
            lineSide: currentLineSide
          };
          this.tracks.set(trackId, bestTrack);
        } else {
          availableTrackIds.delete(bestTrack.id);
          const elapsedMs = Math.max(0, now - bestTrack.lastSeenMs);
          if (line && bestTrack.lineSide !== null && currentLineSide !== 0 && bestTrack.lineSide !== 0) {
            if (bestTrack.lineSide < 0 && currentLineSide > 0) crossingDirection = "negative_to_positive";
            if (bestTrack.lineSide > 0 && currentLineSide < 0) crossingDirection = "positive_to_negative";
          }
          bestTrack.insideDurationMs = isInside && bestTrack.inside
            ? bestTrack.insideDurationMs + elapsedMs
            : 0;
          bestTrack.bbox = detection.bbox;
          bestTrack.lastSeenMs = now;
          bestTrack.inside = isInside;
          if (currentLineSide !== 0) bestTrack.lineSide = currentLineSide;
        }

        return {
          ...detection,
          trackId: bestTrack.id,
          trackDurationSeconds: Math.max(0, now - bestTrack.firstSeenMs) / 1000,
          zoneDurationSeconds: bestTrack.insideDurationMs / 1000,
          insideZone: isInside,
          crossingDirection
        };
      });
    }
  }

  const scope = typeof window === "undefined" ? globalThis : window;
  scope.SentinelleTemporalTracker = TemporalTracker;
  scope.SentinelleTrackingGeometry = Object.freeze({validZone, insideZone, lineSide});
})();
