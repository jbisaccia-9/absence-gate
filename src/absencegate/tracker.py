"""The tracker: boards of rows. Columns are found by TITLE - the same field has a different
internal id on every board - and a vendor may have several rows, one per cycle."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from . import dates


@dataclass
class Row:
    board: str
    row_id: str
    v: dict          # title -> value

    @property
    def link(self) -> str:
        return f"tracker://{self.board}/{self.row_id}"

    @property
    def vendor_id(self) -> str:
        return self.v["Vendor ID"]

    @property
    def expires(self) -> dt.date | None:
        return dates.parse(self.v.get("Certificate expires"))


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def rows(boards: dict) -> list[Row]:
    out = []
    for b, board in boards.items():
        names = board["columns"]
        for r in board["rows"]:
            out.append(Row(b, r["row_id"], {names[c]: x for c, x in r["values"].items()}))
    return out


def current_cycle(all_rows: list[Row]) -> list[Row]:
    """One row per vendor: the latest cycle. Older cycles are history, not work."""
    best: dict[str, Row] = {}
    for r in all_rows:
        k = r.vendor_id
        if k not in best or r.v["Cycle start"] > best[k].v["Cycle start"]:
            best[k] = r
    return sorted(best.values(), key=lambda r: r.link)


def apply(boards: dict, writes: list[dict]) -> None:
    for w in writes:
        board = boards[w["board"]]
        cid = {t: c for c, t in board["columns"].items()}[w["field"]]
        row = next(r for r in board["rows"] if r["row_id"] == w["row_id"])
        row["values"][cid] = w["new"]
