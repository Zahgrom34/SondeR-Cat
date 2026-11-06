"""Run with QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import sondercat as cat
from PySide6.QtCore import QPoint, QPointF, QRect, Qt


def pointer_event(position):
    return SimpleNamespace(button=lambda: Qt.LeftButton,
                           globalPosition=lambda: QPointF(position))


class DragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = cat.QApplication.instance() or cat.QApplication([])

    def setUp(self):
        self.manager = SimpleNamespace(
            cfg={"global": copy.deepcopy(cat.GLOBAL_DEFAULTS),
                 "cats": [dict(cat.CAT_DEFAULTS, pos=[100, 100])]},
            inputs=SimpleNamespace(typing=lambda _: False, key_count=0), save_all=Mock())
        self.window = cat.CatWindow(self.manager, 0)
        self.window.timer.stop()
        self.cursor = QPoint(170, 190)
        self.cursor_patch = patch.object(cat, "QCursor", SimpleNamespace(
            pos=lambda: QPoint(self.cursor)))
        self.cursor_patch.start()
        self.screen = SimpleNamespace(
            availableGeometry=lambda: QRect(-2000, -2000, 5000, 5000),
            geometry=lambda: QRect(-2000, -2000, 5000, 5000))
        self.screen_patch = patch.object(cat, "QGuiApplication", SimpleNamespace(
            screenAt=lambda _: self.screen, screens=lambda: [self.screen]))
        self.screen_patch.start()

    def tearDown(self):
        self.screen_patch.stop()
        self.cursor_patch.stop()
        self.window.close()
        self.window.deleteLater()

    def test_stationary_hold_does_not_slide_or_resize(self):
        start, size = self.window.pos(), self.window.size()
        self.window.mousePressEvent(pointer_event(self.cursor))
        for _ in range(60):
            self.window.tick()
        self.assertEqual(self.window.pos(), start)
        self.assertEqual(self.window.size(), size)
        self.assertEqual(self.window.state, cat.DRAG)

    def test_fast_moves_and_timer_keep_the_same_grab_point(self):
        self.window.mousePressEvent(pointer_event(self.cursor))
        offset = self.cursor - self.window.pos()
        size = self.window.size()
        for point in [QPoint(800, 400), QPoint(-300, 100), QPoint(1200, -200)]:
            self.cursor = point
            self.window.mouseMoveEvent(pointer_event(self.cursor))
            self.assertEqual(self.window.pos() + offset, self.cursor)
            self.window.tick()
            self.assertEqual(self.window.pos() + offset, self.cursor)
            self.assertEqual(self.window.size(), size)

    def test_stale_global_cursor_cannot_pull_drag_downward(self):
        self.window.mousePressEvent(pointer_event(self.cursor))
        grab = self.window.drag_offset
        native_position = QPoint(350, 320)
        self.window.mouseMoveEvent(pointer_event(native_position))
        with patch.object(cat, "global_cursor_position", return_value=QPoint(350, 360)):
            for _ in range(20):
                self.window.tick()
                self.assertEqual(self.window.pos() + grab, native_position)

    def test_dangling_face_stays_at_pre_grab_height_at_all_sizes(self):
        for scale in (2, 6, 10):
            with self.subTest(scale=scale):
                self.window.dragging = False
                self.window.state = cat.IDLE
                self.window._drag_stretch = 1.0
                self.window.scale = scale
                self.window._resize_to_sprite()
                old_frame = self.window._frame_name()
                old_eye_y = cat.sprites.EYE_CELLS[old_frame][0][1]
                self.cursor = self.window.pos() + QPoint(70, 90)
                self.window.mousePressEvent(pointer_event(self.cursor))
                image = self.window._frame_image("dangle", False)
                frame = cat.QImage(self.window.size(), cat.QImage.Format_ARGB32)
                frame.fill(Qt.transparent)
                p = cat.QPainter(frame)
                self.window._draw_reactive_sprite(p, image, self.window.cat_rect(),
                                                  "dangle", False, 0)
                p.end()
                r = self.window.cat_rect()
                x = r.left() + 6 * scale
                y = r.top() + (old_eye_y + 1) * scale
                self.assertEqual(frame.pixelColor(x, y), cat.QColor(self.window.palette()["E"]))

    def test_grab_uses_native_local_position_despite_delayed_window_geometry(self):
        event = pointer_event(QPoint(170, 207))
        event.position = lambda: QPointF(70, 90)
        self.window.mousePressEvent(event)
        self.assertEqual(self.window.drag_offset, QPoint(70, 90))

    def test_catching_a_running_cat_preserves_displayed_head_and_lean(self):
        for key, value in dict(music_mode="off", ai_busy=False, guide_active=False,
                               _ask_box=None, _duck_game=None, pomo_end=None).items():
            setattr(self.manager, key, value)

        def render():
            frame = cat.QImage(self.window.width() + 200, self.window.height() + 200,
                               cat.QImage.Format_ARGB32_Premultiplied)
            frame.fill(Qt.transparent)
            p = cat.QPainter(frame)
            p.translate(100, 100)  # exercise the overflow canvas offset too
            self.window._paint_scene(p)
            p.end()

        for mode in ("chase", "glide"):
            for flip in (False, True):
                for phase in (1.0, 1.1, 1.2):
                    with self.subTest(mode=mode, flip=flip, phase=phase):
                        self.window.dragging = False
                        self.window.state = cat.CHASE if mode == "chase" else cat.IDLE
                        self.window.glide_target = QPoint(800, 400) if mode == "glide" else None
                        self.window.flip = flip
                        self.window._drag_stretch = 1.0
                        self.window._drag_angle = self.window.wobble = 0
                        with patch.object(cat.time, "time", return_value=phase):
                            render()
                            before = QPointF(self.window._last_drawn_head)
                            angle = self.window._render_tilt
                            position, size = self.window.pos(), self.window.size()
                            self.cursor = position + QPoint(90, 120)
                            self.window.mousePressEvent(pointer_event(self.cursor))
                            render()
                        after = self.window._last_drawn_head
                        self.assertAlmostEqual(before.x(), after.x(), places=5)
                        self.assertAlmostEqual(before.y(), after.y(), places=5)
                        self.assertEqual(self.window._drag_angle, angle)
                        self.assertEqual(self.window.pos(), position)
                        self.assertEqual(self.window.size(), size)
                        self.assertIsNone(self.window.glide_target)

    def test_release_without_last_move_and_repeated_grabs(self):
        size = self.window.size()
        for index in range(8):
            self.cursor = self.window.pos() + QPoint(50, 90)
            self.window.mousePressEvent(pointer_event(self.cursor))
            destination = QPoint(250 + index * 20, 300)
            self.window.mouseReleaseEvent(pointer_event(destination))
            self.assertEqual(self.window.pos(), destination - QPoint(50, 90))
            self.assertEqual(self.window.size(), size)
            self.assertFalse(self.window.dragging)
            self.assertEqual(self.window.state, cat.IDLE)
            self.assertEqual((self.window._fx, self.window._fy),
                             (float(self.window.x()), float(self.window.y())))
        self.assertEqual(self.manager.save_all.call_count, 8)

    def test_edges_remain_stable_through_ticks_and_release(self):
        bounds = QRect(93, 220, 1280, 756)
        self.screen = SimpleNamespace(availableGeometry=lambda: bounds,
                                          geometry=lambda: bounds)
        self.window.mousePressEvent(pointer_event(self.cursor))
        size = self.window.size()
        for cursor in [QPoint(93, 220), QPoint(1372, 220),
                       QPoint(93, 975), QPoint(1372, 975)]:
            self.cursor = cursor
            self.window.mouseMoveEvent(pointer_event(cursor))
            expected = self.window.pos()
            for _ in range(20):
                self.window.tick()
                self.assertEqual(self.window.pos(), expected)
                self.assertTrue(bounds.contains(self.window.geometry()))
            self.assertEqual(self.window.size(), size)
        self.window.mouseReleaseEvent(pointer_event(self.cursor))
        self.assertEqual(self.window.pos(), expected)

    def test_monitor_crossing_uses_cursor_screen_and_negative_origins(self):
        self.window.mousePressEvent(pointer_event(self.cursor))
        for bounds, cursor in [(QRect(-1280, -200, 1280, 800), QPoint(-1, -199)),
                               (QRect(0, 0, 1920, 1080), QPoint(1, 1079))]:
            self.screen = SimpleNamespace(availableGeometry=lambda: bounds,
                                          geometry=lambda: bounds)
            self.cursor = cursor
            self.window.mouseMoveEvent(pointer_event(self.cursor))
            self.window.tick()
            self.assertTrue(bounds.contains(self.window.geometry()))

    def test_shared_monitor_edge_does_not_snap(self):
        screens = [SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1280, 800)),
                   SimpleNamespace(availableGeometry=lambda: QRect(1280, 0, 1920, 1080))]
        with patch.object(cat.QGuiApplication, "screens", lambda: screens):
            self.window.mousePressEvent(pointer_event(self.cursor))
            offset = self.window.drag_offset
            for x in range(1250, 1310):
                self.cursor = QPoint(x, 400)
                self.window.mouseMoveEvent(pointer_event(self.cursor))
                self.window.tick()
                self.assertEqual(self.window.pos(), self.cursor - offset)

    def test_movement_drives_swing_and_gravity_settles_it(self):
        self.window.mousePressEvent(pointer_event(self.cursor))
        for _ in range(12):
            self.cursor += QPoint(30, 0)
            self.window.mouseMoveEvent(pointer_event(self.cursor))
            self.window._drag_swing_step(1 / 60)
        self.assertGreater(self.window._drag_angle, 1.0)
        for _ in range(180):
            self.window._drag_swing_step(1 / 60)
        self.assertAlmostEqual(self.window._drag_angle, 0.0, places=2)
        for _ in range(12):
            self.cursor -= QPoint(30, 0)
            self.window.mouseMoveEvent(pointer_event(self.cursor))
            self.window._drag_swing_step(1 / 60)
        self.assertLess(self.window._drag_angle, -1.0)
        self.window.mouseReleaseEvent(pointer_event(self.cursor))
        for _ in range(180):
            self.window._drag_swing_step(1 / 60)
        self.assertEqual(self.window._drag_angle, 0.0)

    def test_swing_is_consistent_at_different_frame_rates(self):
        angles = []
        for fps in (30, 60, 120):
            self.window.move(100, 100)
            self.cursor = QPoint(170, 190)
            self.window.mousePressEvent(pointer_event(self.cursor))
            for _ in range(fps // 2):
                self.cursor += QPoint(1800 // fps, 0)
                self.window.mouseMoveEvent(pointer_event(self.cursor))
                self.window._drag_swing_step(1 / fps)
            angles.append(self.window._drag_angle)
        self.assertLess(max(angles) - min(angles), 0.1)

    def test_holding_at_edge_does_not_keep_driving_swing(self):
        bounds = QRect(0, 0, 1280, 800)
        self.screen = SimpleNamespace(availableGeometry=lambda: bounds,
                                      geometry=lambda: bounds)
        self.window.mousePressEvent(pointer_event(self.cursor))
        self.cursor = bounds.bottomRight()
        self.window.mouseMoveEvent(pointer_event(self.cursor))
        for _ in range(180):
            self.window._drag_swing_step(1 / 60)
        self.assertEqual(self.window._drag_angle, 0.0)
        self.assertEqual(self.window._drag_angular_velocity, 0.0)

    def test_stretch_is_bounded_and_settles_after_release(self):
        size = self.window.size()
        self.window.mousePressEvent(pointer_event(self.cursor))
        for _ in range(30):
            self.cursor += QPoint(0, -70)
            self.window.mouseMoveEvent(pointer_event(self.cursor))
            self.window._drag_swing_step(1 / 60)
        self.assertGreater(self.window._drag_stretch, 1.2)
        self.assertLessEqual(self.window._drag_stretch, 1.6)
        self.assertEqual(self.window.size(), size)
        self.window.mouseReleaseEvent(pointer_event(self.cursor))
        for _ in range(180):
            self.window._drag_swing_step(1 / 60)
        self.assertEqual(self.window._drag_stretch, 1.0)

    def test_body_stretch_does_not_distort_the_head(self):
        source = self.window._frame_image("dangle", False)
        self.window.drag_offset = self.window.cat_rect().topLeft() + QPoint(70, 8)
        self.window._drag_stretch = 1.5
        target = self.window.cat_rect()
        frame = cat.QImage(self.window.width(), self.window.height() + 100,
                           cat.QImage.Format_ARGB32_Premultiplied)
        frame.fill(Qt.transparent)
        p = cat.QPainter(frame)
        self.window._draw_reactive_sprite(p, source, target, "dangle", False, 0)
        p.end()
        head = frame.copy(target.x(), target.y(), source.width(), 15 * self.window.scale)
        self.assertEqual(head.convertToFormat(source.format()),
                         source.copy(0, 0, source.width(), 15 * self.window.scale))
        self.assertTrue(any(frame.pixelColor(x, self.window.height() + 10).alpha()
                            for x in range(frame.width())))

    def test_gaze_tracks_and_keycaps_receive_separate_impulses(self):
        self.cursor = QPoint(2000, -1000)
        for _ in range(30):
            self.window._reaction_step(100.0, 1 / 60)
        self.assertGreater(self.window._gaze_x, 0.9)
        self.assertLess(self.window._gaze_y, -0.9)
        self.manager.inputs.key_count = 1
        self.window._reaction_step(101.0, 1 / 60)
        self.assertEqual(self.window._key_pressed_at[0], 101.0)
        self.manager.inputs.key_count = 2
        self.window._reaction_step(101.1, 1 / 60)
        self.assertEqual(self.window._key_pressed_at[1], 101.1)
        self.assertEqual(len(self.window._key_sparks), 6)
        for _ in range(60):
            self.window._reaction_step(102.0, 1 / 60)
        self.assertEqual(self.window._key_sparks, [])

    def test_typing_effects_leave_window_before_fading(self):
        self.manager.inputs.key_count = 1
        self.window._reaction_step(100, 0)
        for _ in range(20):
            self.window._reaction_step(100.5, 0.025)
        self.assertTrue(any(self.window.cat_rect().left() + spark["x"] < 0
                            and spark["life"] > 0.25 for spark in self.window._key_sparks))


class OverflowTests(unittest.TestCase):
    def test_complete_frame_is_drawn_without_a_cutout(self):
        app = cat.QApplication.instance() or cat.QApplication([])
        overlay = cat.CatOverflow()
        frame = cat.QImage(60, 60, cat.QImage.Format_ARGB32_Premultiplied)
        frame.fill(cat.QColor("#f3dfbf"))
        try:
            overlay.present(frame, QPoint(100, 100), QRect(20, 20, 20, 20))
            result = overlay.grab().toImage()
            self.assertEqual(result.pixelColor(30, 30), frame.pixelColor(30, 30))
            self.assertEqual(result.pixelColor(5, 5), frame.pixelColor(5, 5))
            self.assertTrue(overlay.windowFlags() & Qt.WindowTransparentForInput)
            self.assertTrue(overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        finally:
            overlay.close()


if __name__ == "__main__":
    unittest.main()
