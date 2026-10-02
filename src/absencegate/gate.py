"""The gate. It grades a finished run directory against the inputs it started from and the
portal's own action log. It does not take the worker's word for anything it can check.

  G1 coverage   every current-cycle row gets exactly one outcome, and skips/not-due are true
  G2 evidence   every tracker write traces to a document that was really there and qualifies
  G3 look first a notice only follows a completed look that showed no current certificate
  G4 cadence    one notice per row, numbered from the ledger, under the ceiling and the cap,
                addressed to exactly that row's people
  G5 read-only  nothing outside the allow-list was touched; typing only into the search box
  G6 clean      reports carry links and outcomes, never names, vendor IDs or addresses
  G7 once       (send mode) a live run, and no notice that the send log already holds
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import dates, reader as R, tracker as T, worker as W
from .seed import CLOSURE_TYPE, week_date

RULES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
NAMES = {"G1": "coverage", "G2": "evidence", "G3": "look first", "G4": "cadence",
         "G5": "read-only", "G6": "clean reports", "G7": "once"}
VID = re.compile(r"\bV-\d{5}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass
class Verdict:
    run: str
    failures: dict[str, list[str]] = field(default_factory=dict)

    def fail(self, rule, why):
        self.failures.setdefault(rule, []).append(why)

    @property
    def passed(self):
        return not self.failures

    @property
    def rules_failed(self):
        return [r for r in RULES if r in self.failures]

    def to_json(self):
        return {"run": self.run, "passed": self.passed,
                "rules": {r: {"name": NAMES[r], "passed": r not in self.failures,
                              "failures": self.failures.get(r, [])} for r in RULES}}

    def line(self):
        if self.passed:
            return f"PASS     {self.run}"
        r = self.rules_failed[0]
        more = len(self.failures[r]) - 1
        return (f"REFUSED  {self.run:<28} {','.join(self.rules_failed)}  {self.failures[r][0]}"
                + (f" (+{more} more)" if more > 0 else ""))


def send_key(m: dict) -> str:
    return f"{m['week']}|{m['row']}|{m['notice']}"


def _jl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def _vendor_keys(fixture: dict, row: T.Row) -> list[str]:
    return [k for k, r in fixture["vendors"].items()
            if W._norm(r["portal_id"]) == W._norm(row.vendor_id) or r["name"] == row.v["Vendor"]]


def grade(run_dir: Path, mode: str = "build") -> Verdict:
    run_dir = Path(run_dir)
    v = Verdict(run_dir.name)
    meta = json.loads((run_dir / "run.json").read_text())
    inp = run_dir / "inputs"
    S = json.loads((inp / "settings.json").read_text())
    fixture = json.loads((inp / "portal.json").read_text())
    ledger = json.loads((inp / "reminders.json").read_text())
    week, run_date = meta["week"], week_date(meta["week"])
    rows = {r.link: r for r in T.current_cycle(T.rows(T.load(inp / "tracker.json")))}
    report = _jl(run_dir / "report.jsonl")
    writes = _jl(run_dir / "writes.jsonl")
    outbox = _jl(run_dir / "outbox.jsonl")
    lookups = {l["lookup"]: l for l in _jl(run_dir / "lookups.jsonl") if l.get("lookup")}
    actions = _jl(run_dir / "portal_actions.jsonl")
    by_row = {}
    for r in report:
        by_row.setdefault(r["row"], []).append(r)

    # G1 -------------------------------------------------------------------------------------
    for link in rows:
        if len(by_row.get(link, [])) != 1:
            v.fail("G1", f"{link}: {len(by_row.get(link, []))} outcomes, expected exactly one")
    for link in by_row:
        if link not in rows:
            v.fail("G1", f"{link}: not a current-cycle row")
    for r in report:
        row = rows.get(r["row"])
        if row is None:
            continue
        if r["outcome"] not in W.OUTCOMES:
            v.fail("G1", f"{r['row']}: unknown outcome {r['outcome']}")
        skip = W.skip_reason(row)
        due = W.is_due(row, run_date, S["window_days"])
        if r["outcome"] == "SKIPPED" and r["reason"] != skip:
            v.fail("G1", f"{r['row']}: skipped as {r['reason']!r} but the tracker says {skip!r}")
        if r["outcome"] == "NOT_DUE" and (skip or due):
            v.fail("G1", f"{r['row']}: marked not due but it is {'skippable' if skip else 'due'}")
        if r["outcome"] not in ("SKIPPED", "NOT_DUE") and (skip or not due):
            v.fail("G1", f"{r['row']}: worked although it is {'skippable' if skip else 'not due'}")

    # G2 -------------------------------------------------------------------------------------
    for w in writes:
        row = rows.get(w["row"])
        if row is None:
            v.fail("G2", f"{w['row']}: write to a row that is not current")
            continue
        keys = _vendor_keys(fixture, row)
        visible = {d["doc_id"]: d for k in keys for d in fixture["vendors"][k]["documents"]
                   if d["visible_from_week"] <= week}
        doc = visible.get(w["basis"]["doc_id"])
        if doc is None:
            v.fail("G2", f"{w['row']}: {w['field']} written from {w['basis']['doc_id']}, "
                         f"which this vendor's portal record did not show this week")
            continue
        if w["field"] == "Status":
            c = dates.parse(doc["listed_date"])
            certs = [dates.parse(d["listed_date"]) for d in visible.values()
                     if W.is_cert_label(d) == "exact" and dates.parse(d["listed_date"])]
            last = max(fixture["vendors"][k]["last_activity"] for k in keys)
            if doc["type"] != CLOSURE_TYPE or c is None:
                v.fail("G2", f"{w['row']}: closed on a document that is not a closure notice")
            elif certs and max(certs) >= c:
                v.fail("G2", f"{w['row']}: closed although a certificate is newer than the notice")
            elif W.active_again(row, c, dates.parse(last)):
                v.fail("G2", f"{w['row']}: closed although the tracker or portal shows it active again")
            continue
        if w["field"] not in ("Certificate expires", "On file", "Notes"):
            v.fail("G2", f"{w['row']}: wrote a field this job may not touch: {w['field']!r}")
            continue
        eff = dates.parse(w["basis"].get("effective"))
        if w["basis"]["via"] == "listing":
            if W.is_cert_label(doc) != "exact" or dates.parse(doc["listed_date"]) != eff:
                v.fail("G2", f"{w['row']}: {doc['doc_id']} is not an exact certificate listed on {eff}")
                continue
        else:
            calls = [c for l in lookups.values() if l.get("row") == w["row"]
                     for c in l.get("reader", []) if c["doc_id"] == doc["doc_id"]]
            ok, why = R.validate(calls[-1]["answer"], doc["text"]) if calls else (False, "no reader call")
            if not ok or dates.parse(calls[-1]["answer"]["effective_date"]) != eff:
                v.fail("G2", f"{w['row']}: reader date for {doc['doc_id']} is not grounded ({why})")
                continue
        if w["field"] == "Certificate expires":
            new = dates.parse(w["new"])
            if new != eff + dt.timedelta(days=S["validity_days"]):
                v.fail("G2", f"{w['row']}: expiry {w['new']} is not effective date + validity")
            elif new <= max(row.expires or dt.date.min, run_date):
                v.fail("G2", f"{w['row']}: expiry moved earlier or written stale ({row.v['Certificate expires']} -> {w['new']})")

    # G3 -------------------------------------------------------------------------------------
    if meta.get("held") and outbox:
        v.fail("G3", f"run held ({meta['held']}) but {len(outbox)} notice(s) queued")
    for m in outbox:
        outs = by_row.get(m["row"], [])
        row = rows.get(m["row"])
        if not outs or outs[0]["outcome"] != "NO_DOCUMENT" or row is None:
            v.fail("G3", f"{m['row']}: notice queued for a row whose outcome is not NO_DOCUMENT")
            continue
        lid = outs[0].get("lookup")
        loaded = [a for a in actions if a["lookup"] == lid and a["action"] == "tab:documents"]
        if not loaded or any(a["result"] != "ok" for a in loaded):
            v.fail("G3", f"{m['row']}: notice queued but the documents page did not load "
                         f"({loaded[-1]['result'] if loaded else 'never opened'}) - unknown, not absent")
            continue
        n_docs = sum(d["visible_from_week"] <= week for k in _vendor_keys(fixture, row)
                     for d in fixture["vendors"][k]["documents"])
        if len(loaded) < max(1, -(-n_docs // W.P.PAGE_SIZE)):
            v.fail("G3", f"{m['row']}: notice queued after reading {len(loaded)} of "
                         f"{-(-n_docs // W.P.PAGE_SIZE)} document pages")
            continue
        if lookups.get(lid, {}).get("reader"):
            v.fail("G3", f"{m['row']}: the document reader was involved; it may not trigger a notice")
        floor = max(row.expires or dt.date.min, run_date)
        for k in _vendor_keys(fixture, row):
            for d in fixture["vendors"][k]["documents"]:
                eff = dates.parse(d["listed_date"])
                if d["visible_from_week"] > week:
                    continue
                label = W.is_cert_label(d)
                if label == "exact" and eff and eff + dt.timedelta(days=S["validity_days"]) > floor:
                    v.fail("G3", f"{m['row']}: notice queued while {d['doc_id']} was on file")
                elif label == "near" or (label == "exact" and eff is None):
                    v.fail("G3", f"{m['row']}: notice queued but {d['doc_id']} might be the "
                                 f"certificate and was never read")

    # G4 -------------------------------------------------------------------------------------
    seen, new_threads = {}, 0
    all_ids = {r.vendor_id for r in T.rows(T.load(inp / "tracker.json"))}
    for m in outbox:
        row = rows.get(m["row"])
        seen[m["row"]] = seen.get(m["row"], 0) + 1
        if seen[m["row"]] > 1:
            v.fail("G4", f"{m['row']}: more than one notice this week")
        expected = int(ledger.get(m["row"], 0)) + 1
        if m["notice"] != expected:
            v.fail("G4", f"{m['row']}: notice {m['notice']} but the ledger says this is notice {expected}")
        if m["notice"] > S["ceiling"]:
            v.fail("G4", f"{m['row']}: notice {m['notice']} is past the ceiling of {S['ceiling']}")
        new_threads += m["notice"] == 1
        if row is not None:
            want = (row.v["Account rep email"], [row.v["Owner email"], row.v["Manager email"]],
                    row.v["Thread address"])
            if (m["to"], m["cc"], m["bcc"]) != want:
                v.fail("G4", f"{m['row']}: addressed to someone other than this row's contacts")
            others = set(VID.findall(m["subject"] + m["body"])) - {row.vendor_id}
            if others & all_ids:
                v.fail("G4", f"{m['row']}: notice mentions another vendor {sorted(others)}")
    if new_threads > S["new_thread_cap"]:
        v.fail("G4", f"{new_threads} new threads, cap is {S['new_thread_cap']}")

    # G5 -------------------------------------------------------------------------------------
    searchable = {x for r in rows.values() for x in (r.vendor_id, r.v["Vendor"])}
    for a in actions:
        if a["action"] not in W.P.ALLOWED or a["result"] == "forbidden":
            v.fail("G5", f"portal action {a['action']!r} on {a['target']!r} is not allow-listed")
        if a["action"] == "search_box:type" and a["target"] not in searchable:
            v.fail("G5", "typed into the search box something that is not a tracked vendor")

    # G6 -------------------------------------------------------------------------------------
    banned = {x for r in T.rows(T.load(inp / "tracker.json"))
              for x in (r.vendor_id, r.v["Vendor"], r.v["Account rep email"], r.v["Owner email"],
                        r.v["Manager email"], r.v["Thread address"]) if x}
    for name in ("summary.md", "report.jsonl"):
        text = (run_dir / name).read_text()
        leaks = sorted({b for b in banned if b in text} | set(EMAIL.findall(text)))
        if leaks:
            v.fail("G6", f"{name} carries record details ({len(leaks)} value(s))")

    # G7 -------------------------------------------------------------------------------------
    if mode == "send":
        if meta["dry_run"]:
            v.fail("G7", "this is a dry run; its outbox is never sent")
        log = json.loads(Path(meta["sendlog"]).read_text()) if Path(meta["sendlog"]).exists() else {}
        for m in outbox:
            if send_key(m) in log:
                v.fail("G7", f"{m['row']}: notice {m['notice']} for week {m['week']} was already sent")
    return v


def check_dir(root: Path, mode: str = "build") -> list[Verdict]:
    out = []
    for meta in sorted(Path(root).glob("*/run.json")):
        verdict = grade(meta.parent, mode)
        (meta.parent / "grading.json").write_text(json.dumps(verdict.to_json(), indent=1) + "\n")
        out.append(verdict)
    return out
