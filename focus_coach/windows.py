"""Read the active Windows window and close a distracting tab or app."""

from __future__ import annotations

import time

import psutil
import win32api
import win32con
import win32gui
import win32process

from focus_coach.rules import can_force_close, is_browser

VK_CONTROL = 0x11
VK_W = 0x57


def foreground_window() -> dict:
	"""Return the window the student is looking at right now.

	A missing or protected window comes back as an empty record so the coach
	counts that moment as neutral instead of crashing the loop.
	"""
	try:
		hwnd = win32gui.GetForegroundWindow()
		if not hwnd:
			return _empty()
		title = win32gui.GetWindowText(hwnd) or ""
		_, pid = win32process.GetWindowThreadProcessId(hwnd)
		process = psutil.Process(pid).name()
		return {"hwnd": hwnd, "pid": pid, "title": title, "process": process}
	except (psutil.Error, OSError, win32gui.error):
		return _empty()


def _empty() -> dict:
	"""Return a window record that the rules treat as neutral."""
	return {"hwnd": 0, "pid": 0, "title": "", "process": "python.exe"}


def close_distraction(window: dict) -> str:
	"""Close an off-task browser tab, or the whole app when it is safe.

	Returns closed, warned_only, or failed. Ctrl+W is sent only after this
	process is actually in front, so the keystroke cannot land on another app.
	"""
	process = window.get("process", "")
	hwnd = window.get("hwnd", 0)
	if not hwnd or not can_force_close(process):
		return "warned_only"
	if is_browser(process):
		return "closed" if _close_browser_tab(hwnd) else "failed"
	return "closed" if _close_window(hwnd) else "failed"


def _close_browser_tab(hwnd: int) -> bool:
	"""Put the browser in front and send Ctrl+W once."""
	if not _force_foreground(hwnd):
		return False
	time.sleep(0.2)
	# The keystroke must hit the same window we decided was off task.
	if win32gui.GetForegroundWindow() != hwnd:
		return False
	win32api.keybd_event(VK_CONTROL, 0, 0, 0)
	win32api.keybd_event(VK_W, 0, 0, 0)
	win32api.keybd_event(VK_W, 0, win32con.KEYEVENTF_KEYUP, 0)
	win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
	return True


def _close_window(hwnd: int) -> bool:
	"""Ask a distracting app to close without touching a protected process."""
	try:
		win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
		return True
	except win32gui.error:
		return False


def _force_foreground(hwnd: int) -> bool:
	"""Bring a window forward even when Windows would otherwise block it."""
	try:
		current = win32gui.GetForegroundWindow()
		current_thread = win32process.GetWindowThreadProcessId(current)[0]
		target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
		attached = False
		if current_thread != target_thread:
			win32process.AttachThreadInput(current_thread, target_thread, True)
			attached = True
		win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
		win32gui.SetForegroundWindow(hwnd)
		if attached:
			win32process.AttachThreadInput(current_thread, target_thread, False)
		return win32gui.GetForegroundWindow() == hwnd
	except (win32gui.error, OSError):
		return False


def flash_taskbar(hwnd: int) -> None:
	"""Blink the Focus Coach taskbar button so a nudge is visible if the toast is quiet."""
	try:
		if hwnd:
			win32gui.FlashWindow(hwnd, True)
	except (win32gui.error, OSError):
		return
