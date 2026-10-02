"""The document reader: an LLM that reads INSIDE a document when the listing can't settle a
record. It advises; it never acts. Answers here are recorded, so CI needs no key - a live
reader would sit behind the same validate()."""
from __future__ import annotations

import json
from pathlib import Path

from . import dates

THRESHOLD = 0.85
KEYS = {"is_target_document", "effective_date", "confidence", "evidence"}


class RecordedReader:
    def __init__(self, path: Path):
        self.answers = json.loads(Path(path).read_text())

    def read(self, doc_id: str, text: str) -> dict:
        return dict(self.answers.get(doc_id, {"is_target_document": False, "effective_date": "",
                                              "confidence": 0.0, "evidence": "",
                                              "model": "doc-reader-small", "prompt_version": "r3"}))


def validate(answer: dict, document_text: str) -> tuple[bool, str]:
    """Accepted only if every one of these holds. Each failure has its own reason so a
    person can see why it came to them."""
    if not KEYS <= set(answer):
        return False, "schema"
    if answer["is_target_document"] is not True:
        return False, "not_target"
    eff = dates.parse(answer["effective_date"])
    if eff is None:
        return False, "date_unparseable"
    if not isinstance(answer["confidence"], (int, float)) or answer["confidence"] < THRESHOLD:
        return False, "low_confidence"
    ev = answer["evidence"]
    if not ev or ev not in document_text:
        return False, "evidence_not_in_document"
    if eff not in dates.dates_in(ev):
        return False, "evidence_does_not_state_date"
    return True, "ok"
