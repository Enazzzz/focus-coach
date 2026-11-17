"""Local webcam presence. Frames stay in memory and the camera turns off with the session."""

from __future__ import annotations

import threading
import time

import cv2
from PIL import Image


class DeskCamera:
	"""Watch for a face so the session can tell 'at the desk' from 'stepped away'."""

	def __init__(self):
		"""Start idle, with the camera closed."""
		self._status = "off"
		self._image: Image.Image | None = None
		self._frame_id = 0
		self._lock = threading.Lock()
		self._stop = threading.Event()
		self._thread: threading.Thread | None = None

	def start(self) -> None:
		"""Open the webcam on a background thread."""
		if self._thread and self._thread.is_alive():
			return
		self._stop.clear()
		self._thread = threading.Thread(target=self._run, name="desk-camera", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		"""Release the webcam so the indicator light turns off."""
		self._stop.set()
		if self._thread:
			self._thread.join(timeout=2)
		with self._lock:
			self._status = "off"
			self._image = None

	def status(self) -> str:
		"""Return the latest presence label without copying the preview."""
		with self._lock:
			return self._status

	def snapshot(self) -> tuple[str, Image.Image | None, int]:
		"""Return presence, the current preview, and an id that changes with each new frame.

		The image is replaced rather than edited, so the caller can keep the
		reference and skip work when the id has not changed.
		"""
		with self._lock:
			return self._status, self._image, self._frame_id

	def _run(self) -> None:
		"""Capture a few frames a second and mark whether a face is visible."""
		capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
		if not capture.isOpened():
			capture = cv2.VideoCapture(0)
		if not capture.isOpened():
			with self._lock:
				self._status = "unavailable"
				self._image = None
			return
		capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
		capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
		cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
		cascade = cv2.CascadeClassifier(cascade_path)
		last_detect = 0.0
		misses = 0
		status = "starting"
		try:
			while not self._stop.is_set():
				ok, frame = capture.read()
				if not ok or frame is None:
					with self._lock:
						self._status = "unavailable"
					time.sleep(0.4)
					continue
				# Shrink before anything else. A 720p frame, a face search, and a
				# full-size preview were enough to stall the window and the clock.
				small = cv2.resize(frame, (320, 180))
				now = time.monotonic()
				if now - last_detect >= 1.0:
					last_detect = now
					status, misses = self._presence(cascade, small, status, misses)
				self._publish(small, status)
				time.sleep(0.45)
		finally:
			capture.release()

	def _presence(self, cascade, small, status: str, misses: int) -> tuple[str, int]:
		"""Update at-desk or away. One missed frame does not count as leaving."""
		gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
		faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(24, 24))
		if len(faces):
			x, y, w, h = faces[0]
			cv2.rectangle(small, (x, y), (x + w, y + h), (80, 200, 140), 2)
			return "at_desk", 0
		misses += 1
		# About eight seconds of no face before the session calls it away.
		if misses >= 8:
			return "away", misses
		return status, misses

	def _publish(self, frame, status: str) -> None:
		"""Store a small preview. The clock reads status and does not wait on this image."""
		rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
		image = Image.fromarray(rgb)
		with self._lock:
			self._status = status
			self._image = image
			self._frame_id += 1
