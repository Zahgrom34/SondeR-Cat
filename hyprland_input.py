"""Hyprland activity notifications and cursor polling; never records key text."""
import json
import os
import select
import socket
import threading
import time


EVENTS = {"sondercat-key", "sondercat-key-up", "sondercat-scroll",
          "sondercat-ask", "sondercat-escape", "sondercat-update", "sondercat-restart"}


def map_cursor(cursor, monitors, screens):
    """Convert compositor logical coordinates to Qt/XWayland screen coordinates."""
    x, y = cursor
    for monitor in monitors:
        scale = monitor.get("scale", 1) or 1
        width, height = monitor["width"], monitor["height"]
        if monitor.get("transform", 0) % 2:
            width, height = height, width
        width, height = width / scale, height / scale
        mx, my = monitor["x"], monitor["y"]
        if mx <= x < mx + width and my <= y < my + height:
            screen = next((s for s in screens if s[0] == monitor["name"]), None)
            if screen:
                _, sx, sy, sw, sh = screen
                return (round(sx + (x - mx) * sw / width),
                        round(sy + (y - my) * sh / height))
    return None


class HyprlandInput:
    def __init__(self, on_event, root=None):
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        self.root = root or os.path.join(runtime, "hypr", signature)
        self.on_event = on_event
        self.connected = False
        self.bindings_ready = False
        self.snapshot = None
        self.monitors = []
        self._stop = threading.Event()
        self._thread = None

    @property
    def keyboard_active(self):
        return self.connected and self.bindings_ready

    def request(self, command):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            client.connect(os.path.join(self.root, ".socket.sock"))
            client.sendall(command.encode())
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                data = client.recv(65536)
                if not data:
                    break
                chunks.append(data)
                if sum(map(len, chunks)) > 2_000_000:
                    raise ValueError("Oversized Hyprland response")
        return json.loads(b"".join(chunks))

    def position(self, screens, xwayland=True):
        snapshot = self.snapshot
        if snapshot is None or time.monotonic() - snapshot[2] > 0.3:
            return None
        cursor = snapshot[:2]
        return map_cursor(cursor, self.monitors, screens) if xwayland else cursor

    def dispatch_line(self, line):
        if line.startswith("custom>>"):
            event = line[len("custom>>"):]
            if event in EVENTS:
                self.on_event(event)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="sondercat-hyprland")
        self._thread.start()

    def close(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as events:
                    events.settimeout(0.2)
                    events.connect(os.path.join(self.root, ".socket2.sock"))
                    self.connected = True
                    pending = b""
                    next_poll = next_metadata = 0.0
                    while not self._stop.is_set():
                        now = time.monotonic()
                        if now >= next_metadata:
                            self.monitors = self.request("j/monitors")
                            binds = self.request("j/binds")
                            self.bindings_ready = any(b.get("arg") == "sondercat-key" for b in binds)
                            next_metadata = now + 5
                        if now >= next_poll:
                            cursor = self.request("j/cursorpos")
                            self.snapshot = (int(cursor["x"]), int(cursor["y"]), time.monotonic())
                            next_poll = now + 1 / 30
                        ready, _, _ = select.select([events], [], [], max(0, next_poll - time.monotonic()))
                        if ready:
                            data = events.recv(65536)
                            if not data:
                                break
                            pending += data
                            while b"\n" in pending:
                                line, pending = pending.split(b"\n", 1)
                                self.dispatch_line(line.decode("utf-8", errors="replace"))
                            if len(pending) > 65536:
                                pending = b""
            except (OSError, ValueError, KeyError, TypeError):
                pass
            finally:
                self.connected = self.bindings_ready = False
                self.snapshot = None
            self._stop.wait(1.0)
