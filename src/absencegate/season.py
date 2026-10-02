"""Run the whole synthetic season: every week live, graded, then sent. Scores the held
lookups against what the portal really had - the number a naive job would have got wrong."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from . import dates, gate, orchestrator, seed, worker
from .portal import visible_docs
from .tracker import current_cycle, load, rows


def run(data_dir: Path, out_dir: Path) -> tuple[int, str]:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    seed.write(data_dir)
    fixture = json.loads((data_dir / "portal.json").read_text())
    lines = ["week  " + "  ".join(f"{o[:8]:>8}" for o in worker.OUTCOMES) + "   sent  gate"]
    wrong_if_naive, held_total, ok = 0, 0, True
    for wk in range(1, seed.WEEKS + 1):
        rd = out_dir / f"week-{wk:02d}"
        boards = load(data_dir / "tracker.json")
        links = {r.link: r for r in current_cycle(rows(boards))}
        meta = worker.run(data_dir, wk, rd, live=True)
        v = gate.grade(rd)
        code, text = orchestrator.send(rd)
        ok &= v.passed and code == 0
        for r in (json.loads(x) for x in (rd / "report.jsonl").read_text().splitlines()):
            if r["outcome"] == "HELD":
                held_total += 1
                row = links[r["row"]]
                keys = [k for k, x in fixture["vendors"].items()
                        if worker._norm(x["portal_id"]) == worker._norm(row.vendor_id)]
                floor = max(row.expires or seed.week_date(wk), seed.week_date(wk))
                if any(worker.is_cert_label(d) in ("exact", "near")
                       and (dates.parse(d["listed_date"]) is None or
                            dates.parse(d["listed_date"]) + timedelta(days=365) > floor)
                       for k in keys for d in visible_docs(fixture, k, wk)):
                    wrong_if_naive += 1
        c = meta["counts"]
        sent = text.split()[1] if code == 0 else "-"
        lines.append(f"{wk:>4}  " + "  ".join(f"{c[o]:>8}" for o in worker.OUTCOMES)
                     + f"   {sent:>4}  {'PASS' if v.passed else 'REFUSED'}"
                     + (f"   held: {meta['held']}" if meta["held"] else ""))
    lines += ["", f"held lookups across the season: {held_total}",
              f"  of which the portal actually had a certificate: {wrong_if_naive}",
              "  (a job that treats 'didn't load' as 'not there' would have sent each of those a notice)"]
    return (0 if ok else 1), "\n".join(lines)
