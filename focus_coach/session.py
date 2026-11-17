"""Save a homework session on disk. Photos and the textbook stay in the session folder."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def data_dir() -> Path:
	"""Return the local data directory, creating it if needed."""
	DATA.mkdir(parents=True, exist_ok=True)
	return DATA


@dataclass
class Session:
	"""One homework sitting, including clocks, nudges, and check results."""

	id: str
	goal: str
	pdf_path: str | None
	assignment_path: str | None
	keywords: list[str]
	allowed_titles: list[str] = field(default_factory=list)
	work_minutes: int = 25
	break_minutes: int = 5
	started_at: float = field(default_factory=time.time)
	ended_at: float | None = None
	focused_seconds: float = 0
	wasted_seconds: float = 0
	away_seconds: float = 0
	break_seconds: float = 0
	events: list[dict] = field(default_factory=list)
	checks: list[dict] = field(default_factory=list)
	redo_open: bool = False

	def directory(self) -> Path:
		"""Return this session's folder."""
		path = data_dir() / "sessions" / self.id
		path.mkdir(parents=True, exist_ok=True)
		return path

	def save(self) -> None:
		"""Write the session file and remember it as the latest one."""
		target = self.directory() / "session.json"
		target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
		(data_dir() / "latest.json").write_text(json.dumps({"id": self.id}), encoding="utf-8")

	def add_event(self, kind: str, message: str) -> None:
		"""Append a short event the live screen can show."""
		self.events.append({"at": time.time(), "kind": kind, "message": message})
		self.events = self.events[-40:]


def new_session(
	goal: str,
	pdf_source: str | None,
	assignment_source: str | None,
	keywords: list[str],
	work_minutes: int,
	break_minutes: int,
) -> Session:
	"""Copy the textbook and worksheet into a new session folder."""
	session = Session(
		id=time.strftime("%Y%m%d-%H%M%S"),
		goal=goal.strip(),
		pdf_path=None,
		assignment_path=None,
		keywords=keywords,
		work_minutes=work_minutes,
		break_minutes=break_minutes,
	)
	folder = session.directory()
	if pdf_source:
		dest = folder / Path(pdf_source).name
		shutil.copy2(pdf_source, dest)
		session.pdf_path = str(dest)
	if assignment_source:
		dest = folder / f"assignment{Path(assignment_source).suffix.lower()}"
		shutil.copy2(assignment_source, dest)
		session.assignment_path = str(dest)
	session.save()
	return session


def load_latest() -> dict | None:
	"""Return the most recent saved session, if one exists."""
	pointer = data_dir() / "latest.json"
	path = None
	if pointer.exists():
		try:
			session_id = json.loads(pointer.read_text(encoding="utf-8")).get("id")
			candidate = data_dir() / "sessions" / str(session_id) / "session.json"
			if candidate.exists():
				path = candidate
		except (OSError, json.JSONDecodeError, TypeError):
			path = None
	if path is None:
		found = sorted((data_dir() / "sessions").glob("*/session.json"))
		path = found[-1] if found else None
	if path is None:
		return None
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError, TypeError):
		return None
	if "focused_seconds" not in data:
		data["focused_seconds"] = data.get("focused_s", 0)
		data["wasted_seconds"] = data.get("wasted_s", 0)
		data["away_seconds"] = data.get("away_s", 0)
	return data
