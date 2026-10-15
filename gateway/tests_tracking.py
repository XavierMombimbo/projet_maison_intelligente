from unittest import TestCase
from .tracking import GeometricTracker
from .webcam import PresenceRule


def person(x, *, confidence=0.9, label='person'):
    return {'label': label, 'confidence': confidence, 'bbox': [x, 0.1, 0.1, 0.3]}


class TrackingTests(TestCase):
    def test_two_people_keep_distinct_tracks_when_order_and_confidence_change(self):
        tracker = GeometricTracker()
        first = tracker.update([person(0.1), person(0.7, confidence=0.8)], 10)
        second = tracker.update([person(0.71), person(0.11, confidence=0.7)], 10.5)
        self.assertNotEqual(first[0]['track_id'], first[1]['track_id'])
        self.assertEqual(first[0]['track_id'], second[1]['track_id'])
        self.assertEqual(first[1]['track_id'], second[0]['track_id'])

    def test_disappearance_and_pause_do_not_reuse_presence_from_another_visit(self):
        tracker = GeometricTracker()
        original = tracker.update([person(0.1)], 10)[0]['track_id']
        self.assertEqual(tracker.update([person(0.11)], 11)[0]['track_id'], original)
        after_gap = tracker.update([person(0.11)], 13)[0]['track_id']
        self.assertNotEqual(after_gap, original)
        tracker.reset()
        after_pause = tracker.update([person(0.11)], 13.5)[0]['track_id']
        self.assertNotEqual(after_pause, after_gap)

    def test_classes_and_separate_process_sessions_do_not_share_tracks(self):
        tracker = GeometricTracker()
        human = tracker.update([person(0.1)], 10)[0]['track_id']
        dog = tracker.update([person(0.1, label='dog')], 10.1)[0]['track_id']
        self.assertNotEqual(human, dog)
        another = GeometricTracker().update([person(0.1)], 10)[0]['track_id']
        self.assertNotEqual(human, another)

    def test_tracker_is_bounded_even_when_all_detections_change(self):
        tracker = GeometricTracker(maximum_tracks=2, maximum_center_distance=0.01)
        tracker.update([person(0.1), person(0.3)], 10)
        result = tracker.update([person(0.6), person(0.8), person(0.95)], 10.5)
        self.assertEqual(len(result), 2)
        self.assertLessEqual(len(tracker.tracks), 2)

    def test_second_person_does_not_inherit_first_person_presence(self):
        rule = PresenceRule()
        first = {**person(0.1), 'track_id': 'one'}
        second = {**person(0.7), 'track_id': 'two'}
        analysis = {'presence_seconds': 2}
        self.assertIsNone(rule.evaluate([first], analysis, 10))
        self.assertIsNone(rule.evaluate([first, second], analysis, 11))
        self.assertIsNone(rule.evaluate([second], analysis, 12))
        match = rule.evaluate([second], analysis, 13)
        self.assertEqual(match[1]['track_ids'], ['two'])
        self.assertEqual(match[1]['duration_seconds'], 2)

    def test_leaving_the_zone_resets_presence_even_if_track_remains(self):
        rule = PresenceRule()
        analysis = {'presence_seconds': 2, 'zone': {'x': 0, 'y': 0, 'width': 0.5, 'height': 1}}
        inside = {**person(0.1), 'track_id': 'one'}
        outside = {**person(0.7), 'track_id': 'one'}
        self.assertIsNone(rule.evaluate([inside], analysis, 10))
        self.assertIsNone(rule.evaluate([outside], analysis, 11))
        self.assertIsNone(rule.evaluate([inside], analysis, 12))
        self.assertIsNone(rule.evaluate([inside], analysis, 13))
