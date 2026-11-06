import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hyprland_input import HyprlandInput, map_cursor
import sondercat as cat


class CoordinateTests(unittest.TestCase):
    def setUp(self):
        self.monitors = [
            {"name": "laptop", "x": 93, "y": 176, "width": 1920,
             "height": 1200, "scale": 1.5},
            {"name": "external", "x": 1373, "y": -1, "width": 1920,
             "height": 1080, "scale": 1}]
        self.screens = [("laptop", 0, 0, 1280, 800),
                        ("external", 1280, 0, 1920, 1080)]

    def test_fractional_scaling_and_different_monitor_origins(self):
        self.assertEqual(map_cursor((93, 176), self.monitors, self.screens), (0, 0))
        self.assertEqual(map_cursor((1372, 975), self.monitors, self.screens), (1279, 799))
        self.assertEqual(map_cursor((2124, 820), self.monitors, self.screens), (2031, 821))
        self.assertIsNone(map_cursor((-2000, -2000), self.monitors, self.screens))

    def test_stale_cursor_falls_back_instead_of_freezing(self):
        bridge = HyprlandInput(Mock(), root="/tmp/unused-sondercat-ipc")
        bridge.monitors = self.monitors
        bridge.snapshot = (2124, 820, time.monotonic())
        self.assertEqual(bridge.position(self.screens), (2031, 821))
        bridge.snapshot = (2124, 820, time.monotonic() - 1)
        self.assertIsNone(bridge.position(self.screens))

    def test_compositor_cursor_is_used_when_xwayland_cursor_is_stale(self):
        app = cat.QApplication.instance() or cat.QApplication([])
        bridge = Mock()
        bridge.position.return_value = (500, 300)
        with patch.object(cat, "_HYPR_INPUT", bridge), \
                patch.object(cat.QCursor, "pos", return_value=cat.QPoint(0, 0)):
            self.assertEqual(cat.global_cursor_position(), cat.QPoint(500, 300))


class ActivityTests(unittest.TestCase):
    def test_only_anonymous_known_notifications_are_forwarded(self):
        receive = Mock()
        bridge = HyprlandInput(receive, root="/tmp/unused-sondercat-ipc")
        bridge.dispatch_line("activewindow>>some-app,private title")
        bridge.dispatch_line("custom>>sondercat-key,private text")
        receive.assert_not_called()
        bridge.dispatch_line("custom>>sondercat-key")
        receive.assert_called_once_with("sondercat-key")

    def test_external_keys_drive_typing_and_release_without_key_text(self):
        inputs = SimpleNamespace(key_count=0, key_times=deque(),
                                 on_ask=None, on_esc=None, on_update=None, on_restart=None)
        manager = SimpleNamespace(inputs=inputs, _bridge=SimpleNamespace(poked=Mock()))
        cat.Manager._on_hyprland_input(manager, "sondercat-key")
        self.assertEqual(inputs.key_count, 1)
        self.assertTrue(inputs._external_held)
        self.assertTrue(cat.InputWatcher.typing(inputs, 1))
        cat.Manager._on_hyprland_input(manager, "sondercat-key-up")
        self.assertFalse(inputs._external_held)

    def test_x11_does_not_double_count_when_hyprland_is_connected(self):
        inputs = SimpleNamespace(hyprland=SimpleNamespace(keyboard_active=True))
        # No key data is even inspected when the compositor supplies activity.
        cat.InputWatcher._on_press(inputs, object())
        cat.InputWatcher._on_scroll(inputs, 0, 0, 0, 1)


if __name__ == "__main__":
    unittest.main()
