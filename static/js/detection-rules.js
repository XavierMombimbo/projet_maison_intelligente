(() => {
  "use strict";

  const evaluate = (tracked, config) => {
    const inside = tracked.filter(item => item.insideZone);
    const crossings = inside.filter(item => item.crossingDirection && (
      config.forbiddenCrossingDirection === "any"
      || item.crossingDirection === config.forbiddenCrossingDirection
    ));
    if (crossings.length) {
      return {
        predictions: crossings,
        context: {
          id: "line-crossing",
          version: 1,
          type: "line_crossing",
          duration_seconds: Math.max(...crossings.map(item => item.trackDurationSeconds)),
          zone: config.zone,
          line: config.line,
          direction: crossings[0].crossingDirection,
          track_ids: crossings.map(item => item.trackId)
        }
      };
    }
    const ready = inside.filter(item => item.zoneDurationSeconds >= config.presenceSeconds);
    if (!ready.length) return null;
    return {
      predictions: ready,
      context: {
        id: "presence-zone",
        version: 1,
        type: "presence_prolonged",
        duration_seconds: Math.max(...ready.map(item => item.zoneDurationSeconds)),
        zone: config.zone,
        line: null,
        direction: null,
        track_ids: ready.map(item => item.trackId)
      }
    };
  };

  const scope = typeof window === "undefined" ? globalThis : window;
  scope.SentinelleRuleEvaluator = Object.freeze({evaluate});
})();
