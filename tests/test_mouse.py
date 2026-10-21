from __future__ import annotations

import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock

from core.mouse import (Drag, DragDetector, MouseData, MouseSelectionListener,
                        KeyboardData, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE,
                        WM_KEYDOWN, WM_KEYUP)


class DragDetectorTests(unittest.TestCase):
    @staticmethod
    def click(detector, timestamp, x=10, y=10, target=42):
        detector.feed(WM_LBUTTONDOWN, x, y, time_ms=timestamp, target=target)
        return detector.feed(WM_LBUTTONUP, x, y, time_ms=(timestamp + 20) & 0xFFFFFFFF)

    def test_double_click_triggers_only_on_second_release(self):
        detector = DragDetector()
        self.assertFalse(self.click(detector, 100))
        self.assertFalse(detector.feed(WM_LBUTTONDOWN, 10, 10, time_ms=220, target=42))
        self.assertTrue(detector.feed(WM_LBUTTONUP, 10, 10, time_ms=240))
        self.assertFalse(detector.feed(WM_LBUTTONUP, 10, 10, time_ms=250))
        self.assertEqual(detector.generation, 2)

    def test_separate_clicks_do_not_form_a_double_click(self):
        for timestamp, x, y, target in ((601, 10, 10, 42), (200, 15, 10, 42), (200, 10, 15, 42), (200, 10, 10, 99)):
            with self.subTest(timestamp=timestamp, x=x, y=y, target=target):
                detector = DragDetector()
                self.assertFalse(self.click(detector, 100))
                self.assertFalse(self.click(detector, timestamp, x, y, target))

    def test_double_click_uses_down_times_not_time_between_releases(self):
        detector = DragDetector()
        detector.feed(WM_LBUTTONDOWN, 10, 10, time_ms=100, target=42)
        detector.feed(WM_LBUTTONUP, 10, 10, time_ms=550)
        self.assertFalse(self.click(detector, 650))

    def test_configured_double_click_time_and_rectangle_are_used(self):
        detector = DragDetector(double_click_ms=800, double_click_size=(12, 10))
        self.assertFalse(self.click(detector, 100))
        self.assertTrue(self.click(detector, 850, x=15, y=14))

    def test_event_clock_wraparound_is_supported(self):
        detector = DragDetector()
        self.assertFalse(self.click(detector, 0xFFFFFF80))
        self.assertTrue(self.click(detector, 100))

    def test_reset_and_drag_clear_click_history(self):
        detector = DragDetector()
        self.click(detector, 100)
        detector.reset()
        self.assertFalse(self.click(detector, 200))
        detector.feed(WM_LBUTTONDOWN, 10, 10, time_ms=300, target=42)
        self.assertTrue(detector.feed(WM_LBUTTONUP, 100, 10, time_ms=320))
        self.assertFalse(self.click(detector, 400, x=100))

    def test_second_click_with_drag_emits_only_one_candidate(self):
        detector = DragDetector()
        self.click(detector, 100)
        detector.feed(WM_LBUTTONDOWN, 10, 10, time_ms=200, target=42)
        self.assertFalse(detector.feed(WM_MOUSEMOVE, 100, 10, time_ms=220))
        self.assertTrue(detector.feed(WM_LBUTTONUP, 100, 10, time_ms=240))
        self.assertFalse(self.click(detector, 300, x=100))

    def test_click_and_small_jitter_do_not_trigger(self):
        detector = DragDetector()
        detector.feed(WM_LBUTTONDOWN, 10, 10)
        detector.feed(WM_MOUSEMOVE, 12, 13)
        self.assertFalse(detector.feed(WM_LBUTTONUP, 13, 12))

    def test_drag_triggers_once_and_handles_negative_screen_coordinates(self):
        detector = DragDetector()
        detector.feed(WM_LBUTTONDOWN, -300, 20)
        self.assertFalse(detector.feed(WM_MOUSEMOVE, -200, 20))
        self.assertTrue(detector.feed(WM_LBUTTONUP, -200, 20))
        self.assertFalse(detector.feed(WM_LBUTTONUP, -200, 20))

    def test_new_click_and_reset_invalidate_previous_generation(self):
        detector = DragDetector()
        detector.feed(WM_LBUTTONDOWN, 10, 10)
        generation = detector.generation
        detector.reset()
        self.assertGreater(detector.generation, generation)
        self.assertFalse(detector.feed(WM_LBUTTONUP, 100, 100))


class MouseHookTests(unittest.TestCase):
    def setUp(self):
        self.listener = MouseSelectionListener()
        self.api = Mock()
        self.api.CallNextHookEx.return_value = 123
        self.listener._user32 = self.api
        self.listener.foreground = Mock(return_value=10)
        self.listener.external = Mock(return_value=True)
        self.listener.bounds = Mock(return_value=(0, 0, 100, 100))
        self.api.GetAncestor.return_value = 10
        self.api.WindowFromPoint.return_value = 42
        self.api.GetAsyncKeyState.return_value = 0

    def feed(self, event, x, flags=0, time_ms=0):
        data = MouseData(pt=wintypes.POINT(x, 10), flags=flags, time=time_ms)
        return self.listener._hook_callback(0, event, ctypes.addressof(data))

    def test_hook_emits_candidate_and_always_forwards_input(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.assertEqual(self.feed(WM_LBUTTONDOWN, 10), 123)
        self.assertEqual(self.feed(WM_MOUSEMOVE, 100), 123)
        self.assertEqual(self.feed(WM_LBUTTONUP, 100), 123)
        self.assertEqual(candidates, [Drag(1, 10, (0, 0, 100, 100), (100, 10))])
        self.assertEqual(self.api.CallNextHookEx.call_count, 3)

    def test_hook_emits_one_candidate_for_double_click(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        for event, stamp in ((WM_LBUTTONDOWN, 100), (WM_LBUTTONUP, 120), (WM_LBUTTONDOWN, 200)):
            self.assertEqual(self.feed(event, 10, time_ms=stamp), 123)
        self.assertFalse(candidates)
        self.assertEqual(self.feed(WM_LBUTTONUP, 10, time_ms=220), 123)
        self.assertEqual(candidates, [Drag(2, 10, (0, 0, 100, 100), (10, 10))])
        self.assertEqual(self.api.CallNextHookEx.call_count, 4)

    def test_double_click_across_controls_or_own_window_is_ignored(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.feed(WM_LBUTTONDOWN, 10, time_ms=100)
        self.feed(WM_LBUTTONUP, 10, time_ms=120)
        self.api.WindowFromPoint.return_value = 99
        self.feed(WM_LBUTTONDOWN, 10, time_ms=200)
        self.feed(WM_LBUTTONUP, 10, time_ms=220)
        self.assertFalse(candidates)
        self.listener.external.return_value = False
        self.feed(WM_LBUTTONDOWN, 10, time_ms=300)
        self.feed(WM_LBUTTONUP, 10, time_ms=320)
        self.assertFalse(candidates)

    def test_own_windows_and_injected_drags_are_ignored(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.listener.external.return_value = False
        self.feed(WM_LBUTTONDOWN, 10)
        self.feed(WM_LBUTTONUP, 100)
        self.listener.external.return_value = True
        self.feed(WM_LBUTTONDOWN, 10, flags=1)
        self.feed(WM_LBUTTONUP, 100, flags=1)
        self.assertFalse(candidates)

    def test_hook_exception_and_negative_code_still_forward(self):
        self.listener.foreground.side_effect = RuntimeError("failure")
        self.assertEqual(self.feed(WM_LBUTTONDOWN, 10), 123)
        self.assertEqual(self.listener._hook_callback(-1, WM_LBUTTONDOWN, 0), 123)

    def test_changed_generation_or_moved_window_invalidates_drag(self):
        self.listener._thread = Mock()
        self.listener._thread.is_alive.return_value = True
        self.listener._handle = 1
        self.listener.can_capture = Mock(return_value=True)
        drag = Drag(0, 10, (0, 0, 100, 100))
        self.assertTrue(self.listener.is_current(drag))
        self.listener.bounds.return_value = (10, 10, 110, 110)
        self.assertFalse(self.listener.is_current(drag))
        self.listener.bounds.return_value = drag.bounds
        self.listener.detector.reset()
        self.assertFalse(self.listener.is_current(drag))

    def test_held_keys_or_changed_foreground_prevent_copying(self):
        self.api.GetAsyncKeyState.return_value = 0
        self.assertTrue(self.listener.can_capture(10))
        self.api.GetAsyncKeyState.return_value = 0x8000
        self.assertFalse(self.listener.can_capture(10))
        self.api.GetAsyncKeyState.return_value = 0
        self.listener.foreground.return_value = 20
        self.assertFalse(self.listener.can_capture(10))

    def test_shift_does_not_prevent_uia_but_prevents_copy(self):
        self.api.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 0x10 else 0
        self.assertTrue(self.listener.can_capture(10))
        self.assertFalse(self.listener.can_copy(10))

    def test_drag_can_start_in_an_inactive_window(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.listener.foreground.return_value = 99
        self.feed(WM_LBUTTONDOWN, 10)
        self.listener.foreground.return_value = 10
        self.feed(WM_LBUTTONUP, 100)
        self.assertEqual(candidates[0].window, 10)

    def test_shift_click_and_short_drag_emit_candidates(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.api.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 0x10 else 0
        self.feed(WM_LBUTTONDOWN, 10)
        self.feed(WM_LBUTTONUP, 10)
        self.api.GetAsyncKeyState.return_value = 0
        self.api.GetAsyncKeyState.side_effect = None
        self.feed(WM_LBUTTONDOWN, 10)
        self.feed(WM_LBUTTONUP, 15)
        self.assertEqual(len(candidates), 2)

    def key(self, event, key, flags=0):
        data = KeyboardData(vkCode=key, flags=flags)
        return self.listener._key_callback(0, event, ctypes.addressof(data))

    def test_keyboard_selection_emits_after_release_and_typing_invalidates_it(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.key(WM_KEYDOWN, 0xA0)
        self.key(WM_KEYDOWN, 0x27)
        self.assertFalse(candidates)
        self.assertEqual(self.key(WM_KEYUP, 0x27), 123)
        self.assertEqual(candidates[0].kind, "keyboard")
        self.key(WM_KEYDOWN, ord("X"))
        self.assertGreater(self.listener.detector.generation, candidates[0].generation)

    def test_ctrl_a_and_injected_keys(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.key(WM_KEYDOWN, 0xA2)
        self.key(WM_KEYDOWN, 0x41)
        self.key(WM_KEYUP, 0x41)
        self.assertEqual(len(candidates), 1)
        generation = self.listener.detector.generation
        self.key(WM_KEYDOWN, 0x43, flags=0x10)
        self.assertEqual(self.listener.detector.generation, generation)

    def test_keyboard_selection_does_not_cross_windows(self):
        candidates = []
        self.listener.dragged.connect(candidates.append)
        self.key(WM_KEYDOWN, 0xA0)
        self.key(WM_KEYDOWN, 0x27)
        self.listener.foreground.return_value = 99
        self.key(WM_KEYUP, 0x27)
        self.assertFalse(candidates)

    def test_triple_click_recaptures_paragraph(self):
        detector = DragDetector()
        self.assertFalse(DragDetectorTests.click(detector, 100))
        self.assertTrue(DragDetectorTests.click(detector, 200))
        self.assertTrue(DragDetectorTests.click(detector, 300))
