"""Bounded geometric tracks; a track is never a person's identity."""
import math
import uuid


def overlap(left, right):
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2 = min(left[0] + left[2], right[0] + right[2])
    y2 = min(left[1] + left[3], right[1] + right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = left[2] * left[3] + right[2] * right[3] - intersection
    return intersection / union if union > 0 else 0


def center_distance(left, right):
    return math.hypot(left[0] + left[2] / 2 - right[0] - right[2] / 2,
                      left[1] + left[3] / 2 - right[1] - right[3] / 2)


class GeometricTracker:
    def __init__(self, *, max_missing_seconds=1.2, minimum_iou=0.10,
                 maximum_center_distance=0.15, maximum_tracks=64):
        self.max_missing_seconds = max_missing_seconds
        self.minimum_iou = minimum_iou
        self.maximum_center_distance = maximum_center_distance
        self.maximum_tracks = maximum_tracks
        self.prefix = 'webcam-' + uuid.uuid4().hex[:12]
        self.sequence = 0
        self.tracks = {}

    def reset(self):
        self.tracks.clear()

    def update(self, detections, now):
        if not math.isfinite(now):
            raise ValueError('Horodatage de suivi invalide.')
        self.tracks = {key: item for key, item in self.tracks.items()
                       if 0 <= now - item['last_seen'] <= self.max_missing_seconds}
        available = set(self.tracks)
        candidates = []
        detections = sorted(detections, key=lambda item: item['confidence'], reverse=True)[:self.maximum_tracks]
        for index, detection in enumerate(detections):
            for track_id, track in self.tracks.items():
                if track['label'] != detection['label']:
                    continue
                iou = overlap(track['bbox'], detection['bbox'])
                distance = center_distance(track['bbox'], detection['bbox'])
                if iou >= self.minimum_iou or distance <= self.maximum_center_distance:
                    candidates.append((iou - distance, index, track_id))
        assigned = {}
        for _, index, track_id in sorted(candidates, reverse=True):
            if index not in assigned and track_id in available:
                assigned[index] = track_id
                available.remove(track_id)
        result = []
        for index, detection in enumerate(detections):
            track_id = assigned.get(index)
            if track_id is None:
                if len(self.tracks) >= self.maximum_tracks:
                    oldest = min(available, key=lambda key: self.tracks[key]['last_seen'], default=None)
                    if oldest is None:
                        continue
                    del self.tracks[oldest]
                    available.remove(oldest)
                self.sequence += 1
                track_id = f'{self.prefix}-{self.sequence}'
            self.tracks[track_id] = {'label': detection['label'], 'bbox': list(detection['bbox']),
                                     'last_seen': now}
            result.append({**detection, 'track_id': track_id})
        return result
