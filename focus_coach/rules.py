"""Pure decisions for focus, breaks, and homework verdicts.

These functions do not touch the camera, the screen, or the network, so they
can be tested without a Windows desktop session.
"""

from __future__ import annotations

import re

# Words that show up in almost every homework sentence and should not unlock tabs.
STOPWORDS = {
	"this", "that", "with", "from", "have", "your", "homework", "work",
	"need", "just", "some", "them", "they", "will", "what", "when",
	"where", "which", "about", "into", "over", "also", "page", "pages",
	"problem", "problems", "please", "finish", "today", "study", "class",
	"math", "book", "paper", "actual", "doing", "gonna", "want", "make",
	"sure", "stay", "focused", "working", "thats", "doing", "microsoft",
	"edge", "chrome", "firefox", "google", "open", "currently", "give",
	"personal", "browser", "window", "tab",
}

# Sites and apps that are treated as a drift the moment they are in front.
BLOCKED_KEYWORDS = (
	"youtube", "netflix", "disney+", "hulu", "twitch", "tiktok", "instagram",
	"reddit", "twitter", "facebook", "discord", "steam", "roblox", "minecraft",
	"snapchat", "pinterest", "tumblr", "crunchyroll", "prime video",
)

BLOCKED_PROCESSES = {
	"discord.exe",
	"steam.exe",
	"steamwebhelper.exe",
	"epicgameslauncher.exe",
	"riotclientux.exe",
	"robloxplayerbeta.exe",
	"minecraftlauncher.exe",
}

BROWSER_PROCESSES = {
	"chrome.exe",
	"msedge.exe",
	"firefox.exe",
	"brave.exe",
	"opera.exe",
	"opera_gx.exe",
}

# Tools a homework session is allowed to keep in front.
ALLOWED_PROCESSES = {
	"explorer.exe",
	"notepad.exe",
	"notepad++.exe",
	"winword.exe",
	"excel.exe",
	"powerpnt.exe",
	"onenote.exe",
	"acrord32.exe",
	"acrobat.exe",
	"foxitreader.exe",
	"sumatrapdf.exe",
	"applicationframehost.exe",
	"calculatorapp.exe",
	"screenclippinghost.exe",
	"snippingtool.exe",
	"spotify.exe",
	"photos.exe",
	"mspaint.exe",
}

# Windows shell and this app. These moments are ignored by the clocks.
NEUTRAL_PROCESSES = {
	"python.exe",
	"pythonw.exe",
	"searchhost.exe",
	"startmenuexperiencehost.exe",
	"shellexperiencehost.exe",
	"textinputhost.exe",
	"lockapp.exe",
	"dwm.exe",
	"sihost.exe",
}

# Off task, but never force-closed. Closing an editor can throw away unsaved work.
WARN_ONLY_PROCESSES = {
	"cursor.exe",
	"code.exe",
	"devenv.exe",
	"pycharm64.exe",
	"idea64.exe",
	"cmd.exe",
	"powershell.exe",
	"windowsterminal.exe",
	"wt.exe",
	"taskmgr.exe",
	"ollama.exe",
	"systemsettings.exe",
}

BROWSER_SUFFIXES = (
	" - google chrome",
	" - microsoft edge",
	" — mozilla firefox",
	" - mozilla firefox",
	" - opera",
	" - brave",
)


def keywords_from_text(*parts: str) -> list[str]:
	"""Pull distinctive words out of the homework goal and file names."""
	found: list[str] = []
	seen: set[str] = set()
	for part in parts:
		cleaned = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", part.lower())
		for raw in re.split(r"[^a-z0-9]+", cleaned):
			if raw.isdigit():
				if len(raw) >= 3 and raw not in seen:
					seen.add(raw)
					found.append(raw)
				continue
			if len(raw) < 4 or raw in STOPWORDS or raw in seen:
				continue
			seen.add(raw)
			found.append(raw)
	return found


def simplify_title(title: str) -> str:
	"""Drop the browser name so a whitelist survives small title changes."""
	text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", title.lower()).strip()
	for suffix in BROWSER_SUFFIXES:
		if text.endswith(suffix):
			text = text[: -len(suffix)]
	text = re.sub(r" and \d+ more pages$", "", text)
	text = re.sub(r" - personal$", "", text)
	return text.strip()


def classify_activity(
	process_name: str,
	title: str,
	keywords: list[str],
	allowed_titles: list[str],
) -> str:
	"""Return on_task, off_task, or neutral for the window in front.

	Browsers are on task when the tab title contains a homework keyword or a
	title the student explicitly allowed. Anything else in a browser, and any
	unrecognized app, counts as off task.
	"""
	process = (process_name or "").lower()
	simple = simplify_title(title or "")
	haystack = f"{process} {simple}"

	if "runtime library" in simple or simple.startswith("setup") or simple == "focus coach":
		return "neutral"

	if process in NEUTRAL_PROCESSES:
		return "neutral"

	if process in BLOCKED_PROCESSES or any(word in haystack for word in BLOCKED_KEYWORDS):
		return "off_task"

	for allowed in allowed_titles:
		allowed_simple = simplify_title(allowed)
		if allowed_simple and (allowed_simple in simple or simple in allowed_simple):
			return "on_task"

	if process in ALLOWED_PROCESSES:
		return "on_task"

	if process in BROWSER_PROCESSES:
		if not keywords:
			return "on_task"
		if any(word in simple for word in keywords):
			return "on_task"
		return "off_task"

	return "off_task"


def is_browser(process_name: str) -> bool:
	"""Return whether this process is a desktop browser we can close a tab in."""
	return (process_name or "").lower() in BROWSER_PROCESSES


def can_force_close(process_name: str) -> bool:
	"""Return whether it is safe to ask this process to quit.

	Editors, terminals, and Windows shell windows are warn-only so a nudge
	cannot close Cursor or File Explorer out from under the student.
	"""
	process = (process_name or "").lower()
	if process in NEUTRAL_PROCESSES or process in ALLOWED_PROCESSES or process in WARN_ONLY_PROCESSES:
		return False
	return True


def accumulate(activity: str, presence: str, on_break: bool) -> str:
	"""Choose which clock a second of the session belongs to.

	Away-from-desk time is kept separate from wasted time. A bathroom break
	with the textbook still open should not raise the wasted percentage.
	Looking at Focus Coach itself is neutral, and that time still counts as
	focused. Otherwise the clock freezes for as long as the window is in front.
	"""
	if on_break:
		return "break"
	if activity == "off_task":
		return "wasted"
	if activity == "on_task" and presence == "away":
		return "away"
	if activity in ("on_task", "neutral"):
		return "focused"
	return "ignore"


def wasted_percent(focused_seconds: float, wasted_seconds: float) -> float:
	"""Return the share of active study time spent off task, from 0 to 100."""
	total = focused_seconds + wasted_seconds
	if total <= 0:
		return 0.0
	return round(100.0 * wasted_seconds / total, 1)


class DriftTracker:
	"""Warn once, then ask for a close if the student stays off task."""

	def __init__(self, grace_seconds: float = 20, cooldown_seconds: float = 15):
		"""Remember how long to wait before closing, and how long to stay quiet after."""
		self.grace_seconds = grace_seconds
		self.cooldown_seconds = cooldown_seconds
		self.phase = "clear"
		self.warned_at: float | None = None
		self.cooldown_until = 0.0

	def update(self, now: float, off_task: bool) -> str | None:
		"""Return warn, close, or None for this moment.

		Switching between two off-task windows does not reset the grace timer.
		Coming back to homework clears it.
		"""
		if not off_task:
			self.phase = "clear"
			self.warned_at = None
			return None
		if now < self.cooldown_until and self.phase == "clear":
			return None
		if self.phase == "clear":
			self.phase = "warning"
			self.warned_at = now
			return "warn"
		if self.phase == "warning" and self.warned_at is not None:
			if now - self.warned_at >= self.grace_seconds:
				self.phase = "clear"
				self.warned_at = None
				self.cooldown_until = now + self.cooldown_seconds
				return "close"
		return None

	def seconds_left(self, now: float) -> float | None:
		"""Return how long remains before a close, while a warning is active."""
		if self.phase != "warning" or self.warned_at is None:
			return None
		return max(0.0, self.grace_seconds - (now - self.warned_at))


def break_due(block_started_at: float, now: float, work_minutes: int, on_break: bool) -> bool:
	"""Return whether the work block has reached its break."""
	if on_break:
		return False
	return now - block_started_at >= work_minutes * 60


def break_over(break_started_at: float, now: float, break_minutes: int) -> bool:
	"""Return whether the break timer has finished."""
	return now - break_started_at >= break_minutes * 60


def checkin_due(
	now: float,
	last_checkin_at: float,
	interval_minutes: int,
	on_break: bool,
) -> bool:
	"""Return whether it is time for a spoken check-in."""
	if on_break:
		return False
	return now - last_checkin_at >= interval_minutes * 60


def parse_verdict(text: str) -> dict:
	"""Pull a homework verdict out of a model reply.

	The model is asked for JSON. If it adds a sentence around the object, the
	first object still wins. Unknown verdicts become unreadable so the student
	is asked for another photo instead of a fake pass.
	"""
	import json

	match = re.search(r"\{.*\}", text or "", re.DOTALL)
	if not match:
		return {
			"verdict": "unreadable",
			"hint": "I couldn't read a clear result. Take another photo and try again.",
			"detail": (text or "").strip()[:400],
		}
	try:
		data = json.loads(match.group(0))
	except json.JSONDecodeError:
		return {
			"verdict": "unreadable",
			"hint": "I couldn't read a clear result. Take another photo and try again.",
			"detail": (text or "").strip()[:400],
		}
	verdict = str(data.get("verdict", "unreadable")).lower().strip()
	if verdict not in {"correct", "incorrect", "unreadable"}:
		verdict = "unreadable"
	hint = str(data.get("hint", "")).strip()
	detail = str(data.get("detail", "")).strip()
	if not hint:
		hint = {
			"correct": "This matches the assignment.",
			"incorrect": "Something in the work doesn't match. Redo the problem and submit it again.",
			"unreadable": "Take another photo with the whole problem in frame.",
		}[verdict]
	return {"verdict": verdict, "hint": hint, "detail": detail}


def format_duration(seconds: float) -> str:
	"""Format a duration as a short clock for the session screen."""
	whole = max(0, int(seconds))
	minutes, secs = divmod(whole, 60)
	hours, minutes = divmod(minutes, 60)
	if hours:
		return f"{hours}h {minutes}m"
	return f"{minutes}m {secs:02d}s"
