"""Seven runs that must be refused - each a real run from the seeded season, changed in
exactly one way, and each caught by exactly the rule in its name."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import orchestrator, seed, worker
from .gate import send_key
from .tracker import current_cycle, load, rows

DESCRIPTIONS = {
    "g1-dropped-row": "a row that needed a person silently left out of the report",
    "g2-ungrounded-date": "the reader's date accepted although its quote is not in the document",
    "g3-timeout-as-absent": "the documents page timed out; the run recorded 'no document' and queued a notice",
    "g4-past-the-ceiling": "the ledger shows six notices already; a seventh was queued anyway",
    "g5-clicked-upload": "the browser code touched an upload control on the portal",
    "g6-name-in-summary": "a vendor's name added to the summary that goes to the owners",
    "g7-resend": "a timeout after delivery; the retry would send the same notice again",
}


def _jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def _wjl(p, items):
    Path(p).write_text("".join(json.dumps(x) + "\n" for x in items))


def build(data_dir: Path, out_dir: Path) -> list[str]:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    shutil.rmtree(out_dir, ignore_errors=True)
    seed.write(data_dir)
    worker.run(data_dir, 1, out_dir / "_week1", live=True)
    orchestrator.send(out_dir / "_week1")
    base = out_dir / "_base-week2"
    worker.run(data_dir, 2, base, live=True)          # graded clean; deliberately not sent
    boards = load(base / "inputs" / "tracker.json")
    cur = {r.link: r for r in current_cycle(rows(boards))}
    report = _jl(base / "report.jsonl")

    def copy(name):
        d = out_dir / name
        shutil.copytree(base, d)
        return d

    d = copy("g1-dropped-row")
    gone = next(r for r in report if r["outcome"] == "UNCLEAR")
    _wjl(d / "report.jsonl", [r for r in report if r is not gone])

    d = copy("g2-ungrounded-date")
    r = next(r for r in report if r["reason"] == "reader:evidence_not_in_document")
    lk = next(l for l in _jl(d / "lookups.jsonl") if l.get("lookup") == r["lookup"])
    ans = lk["reader"][0]
    row = cur[r["row"]]
    import datetime as dt
    eff = dt.date.fromisoformat(ans["answer"]["effective_date"])
    basis = {"doc_id": ans["doc_id"], "via": "reader", "effective": str(eff)}
    _wjl(d / "report.jsonl", [dict(x, outcome="ON_FILE", reason="reader") if x is r else x for x in report])
    _wjl(d / "writes.jsonl", _jl(d / "writes.jsonl") + [
        {"board": row.board, "row_id": row.row_id, "row": row.link, "field": "Certificate expires",
         "old": row.v["Certificate expires"], "new": str(eff + dt.timedelta(days=365)),
         "lookup": r["lookup"], "basis": basis}])

    d = copy("g3-timeout-as-absent")
    r = next(r for r in report if r["reason"] == "timeout")
    row = cur[r["row"]]
    _wjl(d / "report.jsonl", [dict(x, outcome="NO_DOCUMENT", reason="notice_1") if x is r else x for x in report])
    _wjl(d / "outbox.jsonl", _jl(d / "outbox.jsonl") + [worker.email(row, 1, seed.week_date(2), 6, 2)])

    d = copy("g4-past-the-ceiling")
    box = _jl(d / "outbox.jsonl")
    target = box[0]
    ledger = json.loads((d / "inputs" / "reminders.json").read_text())
    ledger[target["row"]] = 6
    (d / "inputs" / "reminders.json").write_text(json.dumps(ledger, indent=1))
    _wjl(d / "outbox.jsonl", [worker.email(cur[target["row"]], 7, seed.week_date(2), 6, 2)] + box[1:])

    d = copy("g5-clicked-upload")
    acts = _jl(d / "portal_actions.jsonl")
    _wjl(d / "portal_actions.jsonl", acts + [{"lookup": acts[-1]["lookup"], "action": "doc:upload",
                                              "target": "file-input", "result": "forbidden"}])

    d = copy("g6-name-in-summary")
    who = cur[gone["row"]].v["Vendor"]
    s = (d / "summary.md").read_text().replace(f"{gone['row']} UNCLEAR", f"{gone['row']} ({who}) UNCLEAR")
    (d / "summary.md").write_text(s)

    d = copy("g7-resend")
    first = _jl(d / "outbox.jsonl")[0]
    (d / "sendlog.json").write_text(json.dumps({send_key(first): {"to": first["to"], "week": 2}}))
    meta = json.loads((d / "run.json").read_text())
    meta["sendlog"] = (d / "sendlog.json").as_posix()
    (d / "run.json").write_text(json.dumps(meta, indent=1))

    for tmp in ("_week1", "_base-week2"):
        shutil.rmtree(out_dir / tmp)
    return sorted(DESCRIPTIONS)
