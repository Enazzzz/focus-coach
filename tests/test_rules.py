"""Tests for the decisions that do not need a camera or a desktop."""

import unittest

from focus_coach.rules import (
	DriftTracker,
	accumulate,
	break_due,
	break_over,
	checkin_due,
	classify_activity,
	keywords_from_text,
	parse_verdict,
	wasted_percent,
)


class KeywordTests(unittest.TestCase):
	"""Homework phrases should keep the topic words and drop filler."""

	def test_keeps_topic_words(self) -> None:
		"""Chapter titles become matchable keywords."""
		words = keywords_from_text("Chapter 5 quadratic equations homework")
		self.assertIn("chapter", words)
		self.assertIn("quadratic", words)
		self.assertIn("equations", words)
		self.assertNotIn("homework", words)


class ClassifyTests(unittest.TestCase):
	"""The active window is on task, off task, or ignored."""

	def test_youtube_is_off_task(self) -> None:
		"""A YouTube tab is a drift even if the homework mentions video."""
		activity = classify_activity("chrome.exe", "YouTube - Google Chrome", ["quadratic"], [])
		self.assertEqual(activity, "off_task")

	def test_matching_browser_tab_is_on_task(self) -> None:
		"""A tab whose title contains the topic stays open."""
		activity = classify_activity(
			"chrome.exe",
			"Quadratic equations worksheet - Google Chrome",
			["quadratic", "equations"],
			[],
		)
		self.assertEqual(activity, "on_task")

	def test_random_tab_is_off_task_when_a_topic_exists(self) -> None:
		"""A new tab is off task once the session knows the topic."""
		activity = classify_activity("msedge.exe", "New Tab - Microsoft Edge", ["quadratic"], [])
		self.assertEqual(activity, "off_task")

	def test_pdf_reader_is_on_task(self) -> None:
		"""The textbook app itself is homework."""
		activity = classify_activity("SumatraPDF.exe", "algebra.pdf", ["algebra"], [])
		self.assertEqual(activity, "on_task")

	def test_allowed_title_overrides_a_mismatch(self) -> None:
		"""The student can whitelist the window they say is homework."""
		activity = classify_activity(
			"chrome.exe",
			"Khan Academy - Google Chrome",
			["quadratic"],
			["Khan Academy - Google Chrome"],
		)
		self.assertEqual(activity, "on_task")

	def test_coach_window_is_neutral(self) -> None:
		"""This app must not count itself as wasted time or try to close."""
		activity = classify_activity("pythonw.exe", "Focus Coach", ["quadratic"], [])
		self.assertEqual(activity, "neutral")

	def test_cursor_is_off_task(self) -> None:
		"""An editor is a drift, and the close helper will only warn."""
		activity = classify_activity("Cursor.exe", "focus-coach - Cursor", ["quadratic"], [])
		self.assertEqual(activity, "off_task")


class ClockTests(unittest.TestCase):
	"""Time buckets and the wasted percentage."""

	def test_away_on_homework_is_not_wasted(self) -> None:
		"""Stepping away from an open textbook is its own clock."""
		self.assertEqual(accumulate("on_task", "away", False), "away")

	def test_off_task_is_wasted_even_if_away(self) -> None:
		"""A distracting tab still counts when the chair is empty."""
		self.assertEqual(accumulate("off_task", "away", False), "wasted")

	def test_break_pauses_both_clocks(self) -> None:
		"""Break time is neither focused nor wasted."""
		self.assertEqual(accumulate("off_task", "at_desk", True), "break")

	def test_percent(self) -> None:
		"""Wasted share uses focused plus wasted, and ignores an empty session."""
		self.assertEqual(wasted_percent(75, 25), 25.0)
		self.assertEqual(wasted_percent(0, 0), 0.0)


class DriftTests(unittest.TestCase):
	"""Firm mode warns, waits, then asks for a close."""

	def test_warns_then_closes_after_grace(self) -> None:
		"""Twenty seconds of drift produces one warning and then a close."""
		drift = DriftTracker(grace_seconds=20, cooldown_seconds=15)
		self.assertEqual(drift.update(0, True), "warn")
		self.assertIsNone(drift.update(10, True))
		self.assertEqual(drift.update(20, True), "close")
		self.assertIsNone(drift.update(25, True))

	def test_returning_clears_the_warning(self) -> None:
		"""Coming back to homework cancels the close."""
		drift = DriftTracker(grace_seconds=20)
		drift.update(0, True)
		self.assertIsNone(drift.update(5, False))
		self.assertEqual(drift.update(6, True), "warn")


class ScheduleTests(unittest.TestCase):
	"""Breaks and check-ins follow the clock the student set."""

	def test_break_and_checkin(self) -> None:
		"""A 25 minute block ends on time, and check-ins wait out their interval."""
		self.assertFalse(break_due(0, 24 * 60, 25, False))
		self.assertTrue(break_due(0, 25 * 60, 25, False))
		self.assertFalse(break_due(0, 25 * 60, 25, True))
		self.assertTrue(break_over(0, 5 * 60, 5))
		self.assertFalse(checkin_due(9 * 60, 0, 10, False))
		self.assertTrue(checkin_due(10 * 60, 0, 10, False))
		self.assertFalse(checkin_due(10 * 60, 0, 10, True))


class VerdictTests(unittest.TestCase):
	"""The checker keeps a verdict even when the model adds extra words."""

	def test_parses_json_and_rejects_unknowns(self) -> None:
		"""A fenced reply still yields a redo, and a bad verdict does not pass."""
		parsed = parse_verdict('Sure.\n{"verdict":"incorrect","hint":"Redo the factoring step.","detail":"sign"}')
		self.assertEqual(parsed["verdict"], "incorrect")
		self.assertIn("factoring", parsed["hint"])
		unknown = parse_verdict('{"verdict":"maybe","hint":"hmm","detail":""}')
		self.assertEqual(unknown["verdict"], "unreadable")


if __name__ == "__main__":
	unittest.main()
