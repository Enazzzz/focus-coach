"""On-demand homework check through the local Ollama vision model."""

from __future__ import annotations

import base64
import io
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image

from focus_coach.rules import parse_verdict

OLLAMA_URL = "http://127.0.0.1:11434"
# Qwen3.5 9B is the newer vision model. It reads worksheets better than
# Qwen3-VL 8B, and this quant is 6.6 GB, which fits the 8 GB laptop GPU.
MODEL = "qwen3.5:9b"
CHECK_PROMPT = """You are a homework checker sitting with one student.

You are given the assignment (textbook excerpt and possibly a photo of the worksheet) and a photo of the student's own written work.

Decide whether the written work is correct, incorrect, or unreadable.

Rules:
- If it is incorrect, describe which kind of step went wrong and tell the student to redo that part.
- Do not give the final answer.
- Do not write the corrected solution.
- Do not compute the remaining arithmetic for them.
- If the photo is too blurry or cropped to judge, say unreadable.
- Reply with JSON only, using this shape:
{"verdict":"correct|incorrect|unreadable","hint":"one or two sentences","detail":"what you compared"}
"""


def check_homework(
	goal: str,
	pdf_path: str | None,
	assignment_path: str | None,
	work_path: str,
	keywords: list[str],
) -> dict:
	"""Compare a photo of finished work with the assignment.

	The vision model is started for this call only. The webcam loop never uses it.
	"""
	ensure_ollama()
	images = []
	if assignment_path and Path(assignment_path).exists():
		images.append(_image_b64(assignment_path))
	excerpt, page_image = textbook_context(pdf_path, keywords)
	if page_image is not None:
		images.append(page_image)
	images.append(_image_b64(work_path))
	prompt = (
		CHECK_PROMPT
		+ f"\nHomework goal: {goal}\n"
		+ "The last image is the student's written work. Earlier images are the assignment.\n"
		+ f"\nTextbook excerpt:\n{excerpt or '(no textbook text — use the worksheet photo)'}\n"
	)
	payload = {
		"model": MODEL,
		"messages": [{"role": "user", "content": prompt, "images": images}],
		"stream": False,
		"think": False,
		# Unload after the check. A short context keeps the 9B model on the
		# 8 GB GPU instead of allocating the model's 256K default.
		"keep_alive": 0,
		"options": {"temperature": 0.1, "num_predict": 500, "num_ctx": 8192},
	}
	try:
		response = _post_chat(payload)
	except requests.RequestException as exc:
		raise RuntimeError(_friendly_model_error(exc)) from exc
	body = response.json()
	message = body.get("message") or {}
	text = message.get("content") or message.get("thinking") or ""
	result = parse_verdict(text)
	result["raw"] = text[:800]
	return result


def _post_chat(payload: dict) -> requests.Response:
	"""Send one chat request, retrying without the think flag if this Ollama rejects it."""
	response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=180)
	if response.status_code == 400 and "think" in payload:
		smaller = dict(payload)
		smaller.pop("think", None)
		response = requests.post(f"{OLLAMA_URL}/api/chat", json=smaller, timeout=180)
	response.raise_for_status()
	return response


def textbook_context(pdf_path: str | None, keywords: list[str]) -> tuple[str, str | None]:
	"""Return a short excerpt and, for a scanned book, one page image."""
	if not pdf_path or not Path(pdf_path).exists():
		return "", None
	import fitz

	doc = fitz.open(pdf_path)
	try:
		scored: list[tuple[int, int, str]] = []
		for index, page in enumerate(doc):
			text = page.get_text("text") or ""
			score = sum(text.lower().count(word) for word in keywords) if keywords else 0
			scored.append((score, index, text))
		scored.sort(key=lambda item: item[0], reverse=True)
		chosen = [item for item in scored if item[0] > 0][:3] or scored[:2]
		excerpt = "\n".join(f"--- page {index + 1} ---\n{text.strip()}" for _, index, text in chosen)
		excerpt = excerpt[:6000]
		page_image = None
		# A scanned math book has almost no text. Send one page so the model can still see it.
		if len(excerpt.strip()) < 200 and chosen:
			page = doc[chosen[0][1]]
			pix = page.get_pixmap(dpi=110)
			page_image = base64.b64encode(pix.tobytes("png")).decode("ascii")
		return excerpt, page_image
	finally:
		doc.close()


def ensure_ollama() -> None:
	"""Start the local Ollama app if the checker cannot reach it yet."""
	if _ollama_up():
		_require_model()
		return
	subprocess.Popen(
		["ollama", "list"],
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)
	for _ in range(20):
		time.sleep(0.5)
		if _ollama_up():
			_require_model()
			return
	raise RuntimeError("Ollama is not running. Open the Ollama app, then check the work again.")


def _ollama_up() -> bool:
	"""Return whether the local Ollama API answers."""
	try:
		response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
		return response.ok
	except requests.RequestException:
		return False


def _require_model() -> None:
	"""Fail with a clear message when the vision model is not installed."""
	try:
		response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
		response.raise_for_status()
		names = [item.get("name", "") for item in response.json().get("models", [])]
	except requests.RequestException as exc:
		raise RuntimeError("Ollama is not running. Open the Ollama app, then check the work again.") from exc
	if not any(name == MODEL or name.startswith("qwen3.5") or name.startswith("qwen3-vl") for name in names):
		raise RuntimeError("The vision model is not installed. In a terminal run: ollama pull qwen3.5:9b")


def _image_b64(path: str) -> str:
	"""Shrink a homework photo so the check stays a short burst of work."""
	image = Image.open(path).convert("RGB")
	image.thumbnail((1600, 1600))
	buffer = io.BytesIO()
	image.save(buffer, format="JPEG", quality=85)
	return base64.b64encode(buffer.getvalue()).decode("ascii")


def _friendly_model_error(exc: Exception) -> str:
	"""Turn a network or model failure into a sentence the student can act on."""
	text = str(exc)
	if "11434" in text or "Connection" in text:
		return "Ollama is not running. Open the Ollama app, then check the work again."
	return f"The homework check didn't finish. {text}"
