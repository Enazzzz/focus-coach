"""Focus Coach window."""

from __future__ import annotations

import ctypes
import shutil
import threading
import time
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox

try:
	import customtkinter as ctk
except ImportError as exc:
	import tkinter as tk
	from tkinter import messagebox as _box

	_root = tk.Tk()
	_root.withdraw()
	_box.showerror(
		"Focus Coach",
		"The app dependencies are missing. Double-click run.bat so they can install.",
	)
	raise SystemExit(1) from exc

from focus_coach.checker import check_homework
from focus_coach.engine import FocusEngine
from focus_coach.rules import format_duration, keywords_from_text, wasted_percent
from focus_coach.session import load_latest, new_session

BG = "#12141a"
CARD = "#1b1f2a"
TEXT = "#f4f1ea"
MUTED = "#b7b1a6"
GOOD = "#3ecf8e"
WARN = "#f5b942"
BAD = "#ff6b81"
ACCENT = "#8eb6ff"


class FocusApp(ctk.CTk):
	"""The session window: setup, live watching, homework check, and a recap."""

	def __init__(self):
		"""Build the three screens and show the home page."""
		super().__init__()
		self.title("Focus Coach")
		self.geometry("1080x740")
		self.minsize(960, 640)
		self.configure(fg_color=BG)
		self.engine = FocusEngine()
		self.protocol("WM_DELETE_WINDOW", self._on_close)
		self._refresh_job = None
		self._pdf = ""
		self._paper = ""
		self._photo = None
		self._frame_id = -1
		self._clock_text = ""
		self._percent_text = ""
		self._status_text = ""
		self._pill_text = ""
		self._caption_text = ""
		self._redo_text = ""
		self._log_text = ""
		self.home = self._build_home()
		self.setup_frame = self._build_setup()
		self.live = self._build_live()
		self.summary = self._build_summary()
		self._show(self.home)
		self.after(200, self._remember_hwnd)

	def _remember_hwnd(self) -> None:
		"""Store the real window handle so nudges can blink the taskbar button."""
		try:
			self.engine.app_hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
		except Exception:
			self.engine.app_hwnd = 0

	def _show(self, frame: ctk.CTkFrame) -> None:
		"""Show one full-window screen."""
		for child in (self.home, self.setup_frame, self.live, self.summary):
			child.pack_forget()
		frame.pack(fill="both", expand=True, padx=28, pady=24)

	def _build_home(self) -> ctk.CTkFrame:
		"""Build the opening screen."""
		frame = ctk.CTkFrame(self, fg_color=BG)
		ctk.CTkLabel(frame, text="Focus Coach", font=_font(36, True), text_color=TEXT).pack(anchor="w")
		ctk.CTkLabel(
			frame,
			text=(
				"Start a homework session with your textbook and the worksheet. "
				"While it runs, this window watches which app is in front and whether you are at the desk. "
				"If you drift, it warns you, then closes that tab. "
				"The camera preview stays on screen, and the pictures stay on this PC."
			),
			font=_font(16),
			text_color=MUTED,
			wraplength=900,
			justify="left",
		).pack(anchor="w", pady=(12, 22))
		self.home_last = ctk.CTkLabel(frame, text="", font=_font(15), text_color=TEXT, justify="left")
		self.home_last.pack(anchor="w", pady=(0, 18))
		self._fill_last()
		ctk.CTkButton(
			frame,
			text="Start a session",
			command=self._open_setup,
			fg_color=ACCENT,
			text_color="#101218",
			hover_color="#b7ceff",
			height=48,
			width=220,
			font=_font(16, True),
		).pack(anchor="w")
		return frame

	def _fill_last(self) -> None:
		"""Show the previous session's wasted percentage when one exists."""
		latest = load_latest()
		if not latest:
			self.home_last.configure(text="No sessions yet.")
			return
		percent = wasted_percent(latest.get("focused_seconds", 0), latest.get("wasted_seconds", 0))
		self.home_last.configure(
			text=(
				f"Last session: {latest.get('goal', '')}\n"
				f"Time wasted {percent}%. Focused {format_duration(latest.get('focused_seconds', 0))}."
			)
		)

	def _open_setup(self) -> None:
		"""Open the session form."""
		self._pdf = ""
		self._paper = ""
		self.pdf_label.configure(text="No textbook yet")
		self.paper_label.configure(text="No worksheet photo yet")
		self.goal_box.delete("1.0", "end")
		self.setup_error.configure(text="")
		self._show(self.setup_frame)

	def _build_setup(self) -> ctk.CTkFrame:
		"""Build the form that collects the homework materials."""
		frame = ctk.CTkFrame(self, fg_color=BG)
		ctk.CTkLabel(frame, text="What are you working on?", font=_font(28, True), text_color=TEXT).pack(anchor="w")
		ctk.CTkLabel(
			frame,
			text="Name the topic the way it will show up in the tab or the file. Example: Chapter 5 quadratic equations.",
			font=_font(14),
			text_color=MUTED,
		).pack(anchor="w", pady=(6, 10))
		self.goal_box = ctk.CTkTextbox(frame, height=90, fg_color=CARD, text_color=TEXT, font=_font(15))
		self.goal_box.pack(fill="x")
		row = ctk.CTkFrame(frame, fg_color=BG)
		row.pack(fill="x", pady=16)
		ctk.CTkButton(row, text="Add textbook PDF", command=self._pick_pdf, fg_color=CARD, width=180).pack(side="left")
		self.pdf_label = ctk.CTkLabel(row, text="No textbook yet", text_color=MUTED, font=_font(14))
		self.pdf_label.pack(side="left", padx=12)
		row2 = ctk.CTkFrame(frame, fg_color=BG)
		row2.pack(fill="x", pady=(0, 16))
		ctk.CTkButton(row2, text="Add worksheet photo", command=self._pick_paper, fg_color=CARD, width=180).pack(side="left")
		self.paper_label = ctk.CTkLabel(row2, text="No worksheet photo yet", text_color=MUTED, font=_font(14))
		self.paper_label.pack(side="left", padx=12)
		times = ctk.CTkFrame(frame, fg_color=BG)
		times.pack(fill="x", pady=(4, 8))
		ctk.CTkLabel(times, text="Work block (minutes)", text_color=TEXT, font=_font(14)).pack(side="left")
		self.work_entry = ctk.CTkEntry(times, width=70, fg_color=CARD)
		self.work_entry.insert(0, "25")
		self.work_entry.pack(side="left", padx=(8, 20))
		ctk.CTkLabel(times, text="Break (minutes)", text_color=TEXT, font=_font(14)).pack(side="left")
		self.break_entry = ctk.CTkEntry(times, width=70, fg_color=CARD)
		self.break_entry.insert(0, "5")
		self.break_entry.pack(side="left", padx=8)
		self.setup_error = ctk.CTkLabel(frame, text="", text_color=BAD, font=_font(14))
		self.setup_error.pack(anchor="w", pady=8)
		buttons = ctk.CTkFrame(frame, fg_color=BG)
		buttons.pack(anchor="w", pady=8)
		ctk.CTkButton(buttons, text="Back", command=lambda: self._show(self.home), fg_color=CARD, width=100).pack(side="left", padx=(0, 10))
		ctk.CTkButton(
			buttons,
			text="Start watching",
			command=self._start_session,
			fg_color=ACCENT,
			text_color="#101218",
			hover_color="#b7ceff",
			width=180,
		).pack(side="left")
		return frame

	def _pick_pdf(self) -> None:
		"""Choose the math book PDF."""
		path = filedialog.askopenfilename(title="Textbook PDF", filetypes=[("PDF", "*.pdf")])
		if path:
			self._pdf = path
			self.pdf_label.configure(text=Path(path).name, text_color=TEXT)

	def _pick_paper(self) -> None:
		"""Choose a photo of the worksheet or handwritten prompt."""
		path = filedialog.askopenfilename(
			title="Worksheet photo",
			filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")],
		)
		if path:
			self._paper = path
			self.paper_label.configure(text=Path(path).name, text_color=TEXT)

	def _start_session(self) -> None:
		"""Validate the form and hand the materials to the watcher."""
		goal = self.goal_box.get("1.0", "end").strip()
		if not goal:
			self.setup_error.configure(text="Tell it what the homework is first.")
			return
		try:
			work_minutes = int(self.work_entry.get().strip())
			break_minutes = int(self.break_entry.get().strip())
		except ValueError:
			self.setup_error.configure(text="Work and break need to be whole minutes.")
			return
		if work_minutes < 1 or break_minutes < 1:
			self.setup_error.configure(text="Work and break need at least one minute.")
			return
		keywords = keywords_from_text(goal, Path(self._pdf).stem if self._pdf else "")
		try:
			session = new_session(goal, self._pdf or None, self._paper or None, keywords, work_minutes, break_minutes)
		except OSError as exc:
			self.setup_error.configure(text=f"Couldn't save the homework files. {exc}")
			return
		self.engine.start(session)
		self.goal_live.configure(text=goal)
		self._show(self.live)
		self._schedule_refresh()

	def _build_live(self) -> ctk.CTkFrame:
		"""Build the screen that stays up while a session is running."""
		frame = ctk.CTkFrame(self, fg_color=BG)
		header = ctk.CTkFrame(frame, fg_color=BG)
		header.pack(fill="x")
		self.goal_live = ctk.CTkLabel(header, text="", font=_font(22, True), text_color=TEXT)
		self.goal_live.pack(side="left")
		self.presence_pill = ctk.CTkLabel(header, text="Camera starting", font=_font(13, True), text_color=BG, fg_color=WARN, corner_radius=12)
		self.presence_pill.pack(side="right")
		body = ctk.CTkFrame(frame, fg_color=BG)
		body.pack(fill="both", expand=True, pady=16)
		stats = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16)
		stats.pack(side="left", fill="both", expand=True, padx=(0, 12))
		self.percent_label = ctk.CTkLabel(stats, text="0%", font=_font(72, True), text_color=GOOD)
		self.percent_label.pack(anchor="w", padx=22, pady=(18, 0))
		ctk.CTkLabel(stats, text="time wasted", font=_font(16), text_color=MUTED).pack(anchor="w", padx=24)
		self.clock_label = ctk.CTkLabel(stats, text="", font=_font(15), text_color=TEXT, justify="left")
		self.clock_label.pack(anchor="w", padx=24, pady=12)
		self.status_label = ctk.CTkLabel(stats, text="", font=_font(16), text_color=TEXT, wraplength=460, justify="left")
		self.status_label.pack(anchor="w", padx=24, pady=(4, 8))
		self.redo_label = ctk.CTkLabel(stats, text="", font=_font(15, True), text_color=WARN, wraplength=460, justify="left")
		self.redo_label.pack(anchor="w", padx=24, pady=(0, 16))
		side = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16, width=400)
		side.pack(side="left", fill="y")
		self.preview = ctk.CTkLabel(side, text="Camera preview", text_color=MUTED, width=360, height=240)
		self.preview.pack(padx=16, pady=(16, 8))
		self.camera_caption = ctk.CTkLabel(side, text="", text_color=MUTED, font=_font(13))
		self.camera_caption.pack(anchor="w", padx=16)
		self.log_box = ctk.CTkTextbox(side, width=360, height=180, fg_color=BG, text_color=TEXT, font=_font(13))
		self.log_box.pack(padx=16, pady=12)
		self.log_box.configure(state="disabled")
		buttons = ctk.CTkFrame(frame, fg_color=BG)
		buttons.pack(fill="x")
		ctk.CTkButton(buttons, text="Check my work", command=self._check_work, fg_color=ACCENT, text_color="#101218", hover_color="#b7ceff", width=160).pack(side="left", padx=(0, 8))
		ctk.CTkButton(buttons, text="This is homework", command=self._allow_current, fg_color=CARD, width=160).pack(side="left", padx=8)
		ctk.CTkButton(buttons, text="Take a break", command=self._break_now, fg_color=CARD, width=140).pack(side="left", padx=8)
		ctk.CTkButton(buttons, text="End session", command=self._end_session, fg_color=BAD, text_color="#1a0b10", hover_color="#ff97a8", width=140).pack(side="right")
		return frame

	def _schedule_refresh(self) -> None:
		"""Keep the live numbers moving while a session is open."""
		if not self.live.winfo_ismapped():
			return
		self._draw_live()
		self._refresh_job = self.after(250, self._schedule_refresh)

	def _draw_live(self) -> None:
		"""Paint the latest clocks, status, and camera frame.

		Labels and the preview are left alone when nothing changed. Rebuilding
		the camera image and the log on every tick was what made the window,
		and the clock with it, feel stuck.
		"""
		snap = self.engine.snapshot()
		percent = snap["percent"]
		percent_text = f"{percent:.0f}%" if percent == int(percent) else f"{percent}%"
		if percent_text != self._percent_text:
			self._percent_text = percent_text
			color = GOOD if percent < 15 else WARN if percent < 40 else BAD
			self.percent_label.configure(text=percent_text, text_color=color)
		clock = (
			f"Session {format_duration(snap.get('elapsed', 0))}\n"
			f"Focused {format_duration(snap['focused'])}\n"
			f"Wasted {format_duration(snap['wasted'])}\n"
			f"Away from desk {format_duration(snap['away'])}"
		)
		if clock != self._clock_text:
			self._clock_text = clock
			self.clock_label.configure(text=clock)
		if snap["status_line"] != self._status_text:
			self._status_text = snap["status_line"]
			self.status_label.configure(text=snap["status_line"])
		if snap["redo_open"]:
			redo = "This one needs another try. Fix it, photograph it, and check again."
		elif snap["checks"]:
			redo = "Last check looked right." if snap["checks"][-1].get("verdict") == "correct" else ""
		else:
			redo = ""
		if redo != self._redo_text:
			self._redo_text = redo
			self.redo_label.configure(text=redo)
		presence = snap["presence"]
		pill = {
			"at_desk": ("At the desk", GOOD),
			"away": ("Away from camera", WARN),
			"unavailable": ("No camera", MUTED),
			"off": ("Camera off", MUTED),
			"starting": ("Camera starting", WARN),
		}.get(presence, ("Camera starting", WARN))
		pill_text = f"  {pill[0]}  "
		if pill_text != self._pill_text:
			self._pill_text = pill_text
			self.presence_pill.configure(text=pill_text, fg_color=pill[1], text_color="#101218")
		caption = {
			"at_desk": "Camera is on. The preview is only in this window.",
			"away": "I can't see a face. If you stepped away, this will not count as wasted.",
			"unavailable": "No camera found. Window tracking still runs.",
			"off": "Camera is off.",
			"starting": "Turning the camera on.",
		}.get(presence, "Turning the camera on.")
		if caption != self._caption_text:
			self._caption_text = caption
			self.camera_caption.configure(text=caption)
		_status, image, frame_id = self.engine.camera.snapshot()
		if image is not None and frame_id != self._frame_id:
			self._frame_id = frame_id
			self._photo = ctk.CTkImage(light_image=image, dark_image=image, size=(320, 180))
			self.preview.configure(image=self._photo, text="")
		log = "\n".join(item["message"] for item in snap["events"]) or "Nudges and check-ins show up here."
		if log != self._log_text:
			self._log_text = log
			self.log_box.configure(state="normal")
			self.log_box.delete("1.0", "end")
			self.log_box.insert("1.0", log)
			self.log_box.configure(state="disabled")

	def _allow_current(self) -> None:
		"""Mark the current window as part of the homework."""
		message = self.engine.allow_current()
		self.status_label.configure(text=message)

	def _break_now(self) -> None:
		"""Start the scheduled break early."""
		self.engine.begin_break()

	def _check_work(self) -> None:
		"""Ask for a photo of the finished work and grade it on a background thread."""
		path = filedialog.askopenfilename(
			title="Photo of your work",
			filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp")],
		)
		if not path or self.engine.session is None:
			return
		session = self.engine.session
		dest = session.directory() / f"work-{int(time.time())}{Path(path).suffix.lower()}"
		try:
			shutil.copy2(path, dest)
		except OSError as exc:
			messagebox.showerror("Focus Coach", f"Couldn't save that photo. {exc}")
			return
		dialog = ctk.CTkToplevel(self)
		dialog.title("Check my work")
		dialog.geometry("520x280")
		dialog.configure(fg_color=BG)
		dialog.grab_set()
		label = ctk.CTkLabel(
			dialog,
			text="Checking your page. The fan may spin for a minute, then it stops.",
			font=_font(16),
			text_color=TEXT,
			wraplength=460,
			justify="left",
		)
		label.pack(anchor="w", padx=20, pady=20)

		def work() -> None:
			"""Run the vision model away from the window thread."""
			try:
				result = check_homework(
					session.goal,
					session.pdf_path,
					session.assignment_path,
					str(dest),
					session.keywords,
				)
			except Exception as exc:
				result = {"verdict": "unreadable", "hint": str(exc), "detail": ""}

			def show() -> None:
				"""Show the verdict and record it on the session."""
				self.engine.note_check(result, str(dest))
				if not dialog.winfo_exists():
					return
				title = {
					"correct": "Looks right.",
					"incorrect": "Do this again.",
					"unreadable": "I need a clearer photo.",
				}.get(result.get("verdict"), "Check finished")
				label.configure(text=f"{title}\n\n{result.get('hint', '')}")
				ctk.CTkButton(dialog, text="Done", command=dialog.destroy, fg_color=CARD, width=100).pack(anchor="w", padx=20)

			self.after(0, show)

		threading.Thread(target=work, daemon=True).start()

	def _end_session(self) -> None:
		"""Stop watching and open the recap."""
		if self._refresh_job:
			self.after_cancel(self._refresh_job)
			self._refresh_job = None
		session = self.engine.session
		self.engine.stop()
		self._fill_summary(session)
		self._show(self.summary)

	def _build_summary(self) -> ctk.CTkFrame:
		"""Build the end-of-session recap."""
		frame = ctk.CTkFrame(self, fg_color=BG)
		ctk.CTkLabel(frame, text="Session done", font=_font(32, True), text_color=TEXT).pack(anchor="w")
		self.summary_body = ctk.CTkLabel(frame, text="", font=_font(18), text_color=TEXT, justify="left")
		self.summary_body.pack(anchor="w", pady=18)
		ctk.CTkButton(
			frame,
			text="Back home",
			command=self._back_home,
			fg_color=ACCENT,
			text_color="#101218",
			hover_color="#b7ceff",
			width=160,
		).pack(anchor="w")
		return frame

	def _fill_summary(self, session) -> None:
		"""Write the recap from the session that just ended."""
		if session is None:
			self.summary_body.configure(text="No session was running.")
			return
		percent = wasted_percent(session.focused_seconds, session.wasted_seconds)
		passed = sum(1 for item in session.checks if item.get("verdict") == "correct")
		redos = sum(1 for item in session.checks if item.get("verdict") == "incorrect")
		self.summary_body.configure(
			text=(
				f"{session.goal}\n\n"
				f"Time wasted {percent}%.\n"
				f"Focused {format_duration(session.focused_seconds)}.\n"
				f"Wasted {format_duration(session.wasted_seconds)}.\n"
				f"Away from the desk {format_duration(session.away_seconds)}.\n"
				f"Checks that passed: {passed}. Sent back to redo: {redos}."
			)
		)

	def _back_home(self) -> None:
		"""Return to the start screen and refresh the last-session line."""
		self._fill_last()
		self._show(self.home)

	def _on_close(self) -> None:
		"""Turn the camera off before the window disappears."""
		self.engine.stop()
		self.destroy()


def _font(size: int, bold: bool = False) -> ctk.CTkFont:
	"""Return the app font at one size."""
	return ctk.CTkFont(family="Segoe UI", size=size, weight="bold" if bold else "normal")


def main() -> None:
	"""Open the window, and write a startup log if the window cannot be created."""
	try:
		ctypes.windll.shcore.SetProcessDpiAwareness(1)
	except Exception:
		pass
	try:
		ctk.set_appearance_mode("dark")
		ctk.set_default_color_theme("blue")
		app = FocusApp()
		app.mainloop()
	except Exception:
		log = Path(__file__).resolve().parent.parent / "data"
		log.mkdir(parents=True, exist_ok=True)
		target = log / "startup.log"
		target.write_text(traceback.format_exc(), encoding="utf-8")
		messagebox.showerror("Focus Coach", f"Couldn't start. The details are in {target}")


if __name__ == "__main__":
	main()
