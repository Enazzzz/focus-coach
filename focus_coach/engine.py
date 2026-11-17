"""The running homework session: clocks, nudges, and break timing."""

from __future__ import annotations

import threading
import time

import psutil
import win32gui
import win32process

from focus_coach.camera import DeskCamera
from focus_coach.notify import toast
from focus_coach.rules import (
	DriftTracker,
	accumulate,
	break_due,
	break_over,
	checkin_due,
	classify_activity,
	format_duration,
	simplify_title,
	wasted_percent,
)
from focus_coach.session import Session
from focus_coach.windows import close_distraction, flash_taskbar, foreground_window

CHECKIN_MINUTES = 10
AWAY_NOTICE_SECONDS = 45
GRACE_SECONDS = 20


class FocusEngine:
	"""Watch one session until the student ends it."""

	def __init__(self):
		"""Create an idle engine. The camera stays off until a session starts."""
		self.session: Session | None = None
		self.camera = DeskCamera()
		self.drift = DriftTracker(grace_seconds=GRACE_SECONDS)
		self._lock = threading.Lock()
		self._stop = threading.Event()
		self._thread: threading.Thread | None = None
		self.presence = "off"
		self.activity = "neutral"
		self.window_title = ""
		self.window_process = ""
		self.status_line = "Ready"
		self.on_break = False
		self._block_started = 0.0
		self._break_started = 0.0
		self._last_checkin = 0.0
		self._away_since: float | None = None
		self._away_noted = False
		self._last_tick = 0.0
		self._last_window: dict = {}
		self._last_content: dict = {}
		self.app_hwnd = 0

	def start(self, session: Session) -> None:
		"""Begin cameras, clocks, and the watch loop for this session."""
		self.session = session
		self._stop.clear()
		self.on_break = False
		now = time.time()
		self._block_started = now
		self._last_checkin = now
		self._last_tick = now
		self.drift = DriftTracker(grace_seconds=GRACE_SECONDS)
		self.camera.start()
		self._thread = threading.Thread(target=self._loop, name="focus-engine", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		"""End the watch loop and turn the camera off."""
		self._stop.set()
		if self._thread:
			self._thread.join(timeout=2)
		self.camera.stop()
		with self._lock:
			self.presence = "off"
			if self.session and self.session.ended_at is None:
				self.session.ended_at = time.time()
				self.session.save()

	def allow_current(self) -> str:
		"""Whitelist the window in front for the rest of this session."""
		with self._lock:
			# The button lives in this app, so the window in front is often the coach
			# itself. Whitelist the homework window they were just looking at.
			window = self._last_content or self._last_window
			title = (window.get("title") or "").strip()
			if not title or self.session is None or simplify_title(title) == "focus coach":
				return "Switch to the homework window, then click this."
			if title not in self.session.allowed_titles:
				self.session.allowed_titles.append(title)
				self.session.add_event("allow", f"Allowed: {title}")
				self.session.save()
			self.drift.phase = "clear"
			self.drift.warned_at = None
			self._last_content = {}
			return f"Allowed for this session: {title}"

	def begin_break(self) -> None:
		"""Start a break early. Nudges pause until it ends."""
		with self._lock:
			if self.session is None or self.on_break:
				return
			self._start_break(time.time())

	def snapshot(self) -> dict:
		"""Copy the numbers the window draws."""
		with self._lock:
			session = self.session
			focused = session.focused_seconds if session else 0
			wasted = session.wasted_seconds if session else 0
			away = session.away_seconds if session else 0
			events = list(session.events) if session else []
			redo = session.redo_open if session else False
			goal = session.goal if session else ""
			checks = list(session.checks) if session else []
			left = self.drift.seconds_left(time.time())
			elapsed = max(0.0, time.time() - session.started_at) if session else 0.0
			return {
				"goal": goal,
				"elapsed": elapsed,
				"presence": self.presence,
				"activity": self.activity,
				"title": self.window_title,
				"process": self.window_process,
				"status_line": self.status_line,
				"on_break": self.on_break,
				"focused": focused,
				"wasted": wasted,
				"away": away,
				"percent": wasted_percent(focused, wasted),
				"events": events[-8:],
				"redo_open": redo,
				"checks": checks,
				"grace_left": left,
				"preview": None,
			}

	def note_check(self, result: dict, image_path: str) -> None:
		"""Store a homework check and remember when a redo is still open."""
		with self._lock:
			if self.session is None:
				return
			self.session.checks.append({
				"at": time.time(),
				"verdict": result.get("verdict"),
				"hint": result.get("hint"),
				"image": image_path,
			})
			self.session.redo_open = result.get("verdict") != "correct"
			label = {
				"correct": "Check passed",
				"incorrect": "Redo requested",
				"unreadable": "Photo needs another try",
			}.get(result.get("verdict"), "Check finished")
			self.session.add_event("check", f"{label}: {result.get('hint', '')}")
			self.session.save()

	def _loop(self) -> None:
		"""Sample the active window a few times a second and update the clocks."""
		while not self._stop.is_set():
			now = time.time()
			window = foreground_window()
			presence = self.camera.status()
			self._tick(now, window, presence)
			time.sleep(0.25)

	def _tick(self, now: float, window: dict, presence: str) -> None:
		"""Apply one sample: clocks, break changes, and a nudge if needed."""
		with self._lock:
			session = self.session
			if session is None:
				return
			dt = min(2.0, max(0.0, now - self._last_tick))
			self._last_tick = now
			self._last_window = window
			self.window_title = window.get("title") or ""
			self.window_process = window.get("process") or ""
			self.presence = presence
			activity = classify_activity(
				self.window_process,
				self.window_title,
				session.keywords,
				session.allowed_titles,
			)
			self.activity = activity
			if activity != "neutral":
				self._last_content = dict(window)
			bucket = accumulate(activity, presence, self.on_break)
			if bucket == "focused":
				session.focused_seconds += dt
			elif bucket == "wasted":
				session.wasted_seconds += dt
			elif bucket == "away":
				session.away_seconds += dt
			elif bucket == "break":
				session.break_seconds += dt
			self._update_presence_note(now, presence)
			if self.on_break:
				self.status_line = "Break. Nudges are paused."
				if break_over(self._break_started, now, session.break_minutes):
					self._end_break(now)
			else:
				self._update_work(now, activity, window)
			if now - getattr(self, "_last_save", 0) >= 10:
				self._last_save = now
				session.save()

	def _update_work(self, now: float, activity: str, window: dict) -> None:
		"""Handle drift, check-ins, and the scheduled break while work is on."""
		session = self.session
		assert session is not None
		if break_due(self._block_started, now, session.work_minutes, self.on_break):
			self._start_break(now)
			return
		if checkin_due(now, self._last_checkin, CHECKIN_MINUTES, self.on_break):
			self._last_checkin = now
			message = f"Still on {session.goal}? If you finished a problem, use Check my work."
			session.add_event("checkin", message)
			self.status_line = message
			self._notify("Check-in", message)
		# Looking at this window should not cancel a close that is already aimed
		# at a distracting tab sitting behind it.
		drift_off = activity == "off_task" or (
			activity == "neutral" and self._content_still_off_task(session)
		)
		action = self.drift.update(now, drift_off)
		if action == "warn":
			left = int(GRACE_SECONDS)
			subject = self._last_content if activity == "neutral" and self._last_content else window
			name = subject.get("title") or subject.get("process") or "that window"
			message = (
				f"Hey — are you supposed to be doing that? {name}. "
				f"I'll close it in {left} seconds if you stay there."
			)
			session.add_event("nudge", message)
			self.status_line = message
			self._notify("Hey — are you supposed to be doing that?", message)
		elif action == "close":
			target = self._last_content if self._content_still_off_task(session) else window
			self._close_current(target)
		elif drift_off:
			left = self.drift.seconds_left(now)
			if left is not None:
				self.status_line = f"Off task. Closing in {int(left)}s unless you switch back."
		elif activity == "on_task":
			self.status_line = f"On task. {self.window_title or 'Homework'}."
		elif presence == "away":
			self.status_line = "Homework is up, and I can't see you at the desk."
		else:
			self.status_line = "Watching."

	def _content_still_off_task(self, session: Session) -> bool:
		"""Return whether the last real window is still open on a distraction."""
		return self._window_is_off_task(self._last_content, session)

	def _window_is_off_task(self, window: dict, session: Session) -> bool:
		"""Re-read a window handle and classify whatever it is showing now.

		Chrome keeps the same window handle when the tab changes, so the title
		is checked again before a close. A tab they already left alone is left alone.
		"""
		hwnd = window.get("hwnd") or 0
		if not hwnd:
			return False
		try:
			if not win32gui.IsWindow(hwnd):
				return False
			title = win32gui.GetWindowText(hwnd) or ""
			_, pid = win32process.GetWindowThreadProcessId(hwnd)
			process = psutil.Process(pid).name()
		except (psutil.Error, OSError, win32gui.error):
			return False
		window["title"] = title
		window["process"] = process
		return classify_activity(process, title, session.keywords, session.allowed_titles) == "off_task"

	def _close_current(self, window: dict) -> None:
		"""Close the off-task tab or app, then say what happened.

		The distracting window does not have to be in front already. The close
		helper brings it forward, and it only sends Ctrl+W after that succeeds.
		"""
		session = self.session
		assert session is not None
		if not self._window_is_off_task(window, session):
			self.drift.phase = "clear"
			self.drift.warned_at = None
			return
		result = close_distraction(window)
		title = window.get("title") or window.get("process") or "that window"
		if result == "closed":
			message = f"Closed {title}. Back to {session.goal}."
			session.add_event("close", message)
		elif result == "warned_only":
			message = f"I won't close {title}. Switch back to the homework — this still counts as wasted."
			session.add_event("close", message)
		else:
			message = f"I couldn't close {title}. Switch back yourself. This still counts as wasted."
			session.add_event("close_failed", message)
		self.status_line = message
		self._notify("Focus Coach", message)

	def _start_break(self, now: float) -> None:
		"""Pause nudges and tell the student to step away."""
		session = self.session
		assert session is not None
		self.on_break = True
		self._break_started = now
		self.drift.phase = "clear"
		self.drift.warned_at = None
		message = f"Time for a {session.break_minutes} minute break. Step away from the desk."
		session.add_event("break", message)
		self.status_line = message
		self._notify("Break", message)

	def _end_break(self, now: float) -> None:
		"""Resume firm watching after the break timer."""
		session = self.session
		assert session is not None
		self.on_break = False
		self._block_started = now
		self._last_checkin = now
		message = f"Break's over. Back to: {session.goal}"
		session.add_event("break_end", message)
		self.status_line = message
		self._notify("Back to work", message)

	def _update_presence_note(self, now: float, presence: str) -> None:
		"""Mention a long absence once, without calling it wasted time."""
		if presence != "away" or self.on_break:
			self._away_since = None
			self._away_noted = False
			return
		if self._away_since is None:
			self._away_since = now
		if not self._away_noted and now - self._away_since >= AWAY_NOTICE_SECONDS:
			self._away_noted = True
			message = "I can't see you at the desk. This pause won't count as wasted time."
			if self.session:
				self.session.add_event("away", message)
			self._notify("Still there?", message)

	def _notify(self, title: str, message: str) -> None:
		"""Toast and blink the taskbar. The live screen shows the same sentence."""
		toast(title, message)
		flash_taskbar(self.app_hwnd)

	def summary_line(self) -> str:
		"""Return a one-line recap for the end of a session."""
		with self._lock:
			if self.session is None:
				return ""
			percent = wasted_percent(self.session.focused_seconds, self.session.wasted_seconds)
			return (
				f"Time wasted {percent}%. "
				f"Focused {format_duration(self.session.focused_seconds)}. "
				f"Away {format_duration(self.session.away_seconds)}."
			)
