"""Windows toast notifications. The in-app banner is the one that always shows."""

from __future__ import annotations


def toast(title: str, message: str) -> None:
	"""Show a Windows notification. Failure is ignored because the app banner remains."""
	try:
		from winotify import Notification

		notice = Notification(
			app_id="Focus Coach",
			title=title,
			msg=message,
			duration="short",
		)
		notice.show()
	except Exception:
		return
