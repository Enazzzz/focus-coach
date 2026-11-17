"""Unit tests for the decisions that do not need a camera or a window."""

from __future__ import annotations

import unittest

from focus_coach.rules import (
	DriftTracker,
	accumulate,
	can_force_close,
	classify_activity,
	keywords_from_text,
	parse_verdict,
	wasted_percent,
)


class KeywordTests(unittest.TestCase):
	"""Homework words used to recognize the right browser tab."""

	def test_keeps_distinctive_words(self) -> None:
		"""Generic words drop out; the topic and the book name stay."""
		words = keywords_from_text("Quadratics homework", "Algebra_Book.pdf")
		self.assertIn("quadratics", words)
		self.assertIn("algebra", words)
		self.assertNotIn("homework", words)
		self.assertNotIn("book", words)


class ClassifyTests(unittest.TestCase):
	"""Window classification for firm mode."""

	def test_youtube_is_off_task(self) -> None:
		"""A known distraction site stays off task."""
		result = classify_activity("chrome.exe", "Quadratics - YouTube", ["quadratics"], [])
		self.assertEqual(result, "off_task")

	def test_browser_without_keyword_is_off_task(self) -> None:
		"""A random tab is off task once the goal has real keywords."""
		result = classify_activity("msedge.exe", "New tab - Microsoft Edge", ["quadratics"], [])
		self.assertEqual(result, "off_task")

	def test_matching_browser_tab_is_on_task(self) -> None:
		"""A tab whose title contains the topic is on task."""
		result = classify_activity("chrome.exe", "Quadratics practice problems", ["quadratics"], [])
		self.assertEqual(result, "on_task")

	def test_word_is_on_task(self) -> None:
		"""The word processor is treated as homework."""
		result = classify_activity("WINWORD.EXE", "Essay.docx - Word", ["quadratics"], [])
		self.assertEqual(result, "on_task")

	def test_editor_is_off_task_but_not_closed(self) -> None:
		"""An editor counts as off task, and the coach will not close it."""
		result = classify_activity("Cursor.exe", "chat", ["quadratics"], [])
		self.assertEqual(result, "off_task")
		self.assertFalse(can_force_close("Cursor.exe"))
		self.assertTrue(can_force_close("chrome.exe"))


class ClockBucketTests(unittest.TestCase):
	"""Which clock a second belongs to."""

	def test_looking_at_the_coach_still_counts(self) -> None:
		"""The coach window is neutral, and that time still moves the focused clock."""
		self.assertEqual(accumulate("neutral", "at_desk", False), "focused")

	def test_confirmed_away_is_not_wasted(self) -> None:
		"""Stepping away from homework does not raise the wasted percentage."""
		self.assertEqual(accumulate("on_task", "away", False), "away")


class PercentTests(unittest.TestCase):
	"""Wasted-time percentage."""

	def test_half(self) -> None:
		"""Equal focused and wasted time is 50 percent."""
		self.assertEqual(wasted_percent(30, 30), 50)

	def test_empty(self) -> None:
		"""No scored time yet is 0 percent."""
		self.assertEqual(wasted_percent(0, 0), 0)


class DriftTests(unittest.TestCase):
	"""Warn, then close, without firing again during the cooldown."""

	def test_warn_then_close(self) -> None:
		"""A close is requested only after the grace period."""
		drift = DriftTracker(grace_seconds=20, cooldown_seconds=8)
		self.assertEqual(drift.update(0, True), "warn")
		self.assertIsNone(drift.update(10, True))
		self.assertEqual(drift.update(20, True), "close")

	def test_returning_cancels(self) -> None:
		"""Coming back to homework clears the warning."""
		drift = DriftTracker(grace_seconds=20)
		drift.update(0, True)
		self.assertIsNone(drift.update(5, False))
		self.assertEqual(drift.phase, "clear")

	def test_cooldown_after_close(self) -> None:
		"""A new warning waits until the cooldown ends."""
		drift = DriftTracker(grace_seconds=20, cooldown_seconds=8)
		drift.update(0, True)
		drift.update(20, True)
		self.assertIsNone(drift.update(21, True))
		self.assertEqual(drift.update(29, True), "warn")


class VerdictTests(unittest.TestCase):
	"""Parser for the homework checker's JSON."""

	def test_parses_json_object(self) -> None:
		"""A verdict object is accepted even with surrounding text."""
		raw = 'Here you go {"verdict":"incorrect","hint":"Recheck the sign.","detail":"Line 2"} thanks'
		parsed = parse_verdict(raw)
		self.assertEqual(parsed["verdict"], "incorrect")
		self.assertEqual(parsed["hint"], "Recheck the sign.")

	def test_unknown_verdict_becomes_unreadable(self) -> None:
		"""A verdict outside the three allowed values is treated as unreadable."""
		parsed = parse_verdict('{"verdict":"maybe"}')
		self.assertEqual(parsed["verdict"], "unreadable")


if __name__ == "__main__":
	unittest.main()
