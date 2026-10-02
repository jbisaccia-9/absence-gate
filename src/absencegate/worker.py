"""The weekly worker. It reads, looks, decides and writes files. It never sends mail: queued
messages go to an outbox and the orchestrator sends them. Dry run is the default."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from . import dates, portal as P, reader as R, tracker as T
from .seed import CERT_TYPES, CLOSURE_TYPE, LOOKALIKES, PORTAL, week_date

SETTINGS = {
    "window_days": 45,        # due if the certificate expires within this window
    "validity_days": 365,     # a certificate's effective date + this = its expiry
    "ceiling": 6,             # notices per vendor before it goes to a person instead
    "new_thread_cap": 10,     # caps limit NEW email threads, never checks
    "stop_after": 4,          # consecutive page failures that stop the lookups
    "portal_user_env": "PORTAL_USER", "portal_otp_env": "PORTAL_OTP_SEED",
}
OUTCOMES = ("SKIPPED", "NOT_DUE", "ON_FILE", "CLOSED", "NO_DOCUMENT", "DEFERRED", "UNCLEAR", "HELD")


def _norm(vid: str) -> str:
    return vid.replace("-", "").upper()


def is_cert_label(doc: dict) -> str:
    """'exact' | 'lookalike' | 'near' | ''. Type first, then notes, then file name. Only an
    exact phrase counts; known look-alikes are refused before anything else is considered."""
    fields = [doc["type"], doc["notes"], doc["file_name"].rsplit(".", 1)[0]]
    if any(f in LOOKALIKES for f in fields):
        return "lookalike"
    if any(f in CERT_TYPES for f in fields):
        return "exact"
    low = " ".join(fields).lower()
    if doc["type"] != CLOSURE_TYPE and ("insur" in low or "cert" in low or "coi" in low.split()):
        return "near"
    return ""


def skip_reason(row: T.Row) -> str | None:
    if row.v["Status"] == "Closed":
        return "closed"
    if row.v["Group"].startswith("Archive"):
        return "archived"
    if row.v["Scope"] != "Required":
        return "out_of_scope"
    return None


def is_due(row: T.Row, run_date: dt.date, window: int) -> bool:
    exp = row.expires                      # missing or unreadable = assume not on file
    return exp is None or exp <= run_date + dt.timedelta(days=window)


def active_again(row: T.Row, closure: dt.date, last_activity: dt.date | None) -> bool:
    return (row.v["Renewal pending"] == "yes" or row.v["Hold"] == "yes"
            or (dates.parse(row.v["Cycle start"]) or dt.date.min) > closure
            or (last_activity or dt.date.min) > closure)


def run(data_dir: Path, week: int, out_dir: Path, live: bool = False, settings: dict | None = None) -> dict:
    S = {**SETTINGS, **(settings or {})}
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    shutil.rmtree(out_dir, ignore_errors=True)
    (out_dir / "inputs").mkdir(parents=True)
    for f in ("tracker.json", "portal.json", "reminders.json", "reader_answers.json"):
        shutil.copy(data_dir / f, out_dir / "inputs" / f)
    (out_dir / "inputs" / "settings.json").write_text(json.dumps(S, indent=1) + "\n")

    run_date = week_date(week)
    boards = T.load(data_dir / "tracker.json")
    fixture = json.loads((data_dir / "portal.json").read_text())
    ledger = json.loads((data_dir / "reminders.json").read_text())
    reader = R.RecordedReader(data_dir / "reader_answers.json")
    portal = P.MockPortal(fixture, week, out_dir / "portal_actions.jsonl")

    report, writes, outbox, lookups, resets = [], [], [], [], []
    rows = T.current_cycle(T.rows(boards))
    due = []
    for row in rows:
        why = skip_reason(row)
        if why:
            report.append({"row": row.link, "outcome": "SKIPPED", "reason": why})
        elif not is_due(row, run_date, S["window_days"]):
            report.append({"row": row.link, "outcome": "NOT_DUE", "reason": ""})
        else:
            due.append(row)

    held_run = None
    try:
        portal.login(S["portal_user_env"], S["portal_otp_env"])
    except P.PortalDown:
        held_run = "portal_unreachable"

    streak, new_threads, stopped = 0, 0, False
    for i, row in enumerate(due):
        if held_run or stopped:
            report.append({"row": row.link, "outcome": "HELD",
                           "reason": held_run or "stopped_after_failures"})
            continue
        lid = f"L{week:02d}-{i:03d}"
        portal.lookup = lid
        lk = {"lookup": lid, "row": row.link, "at": f"{run_date}T07:{i // 60:02d}:{i % 60:02d}",
              "complete": False, "error": None, "reader": []}
        lookups.append(lk)

        def finish(outcome, reason="", step=""):
            report.append({"row": row.link, "outcome": outcome, "reason": reason, "lookup": lid,
                           **({"step": step} if step else {})})

        # ---- find the vendor: by ID, then an exact name with exactly one result ----------
        hits = [k for k in portal.search(row.vendor_id)]
        if not hits:
            hits = [k for k in portal.search(row.v["Vendor"])]
            lk["search_by"] = "name"
        else:
            lk["search_by"] = "id"
        if len(hits) != 1:
            finish("UNCLEAR", "no_match" if not hits else "multiple_matches")
            continue
        key = hits[0]
        try:
            page = portal.open(key)
            for n in range(2, page["pages"] + 1):          # every page, or it isn't a look
                page["listing"] += portal.page(key, n)
        except P.PageError as e:
            lk["error"] = str(e)
            streak += 1
            finish("HELD", e.kind, e.step)
            if streak >= S["stop_after"]:
                stopped = True
            continue
        streak = 0
        if _norm(page["shown_id"]) != _norm(row.vendor_id):
            lk["complete"] = True
            finish("UNCLEAR", "id_mismatch")
            continue
        lk["complete"] = True

        # ---- read the listing ---------------------------------------------------------
        best, closure, reader_used, reader_failed = None, None, False, None
        latest_any_cert = None
        for doc in page["listing"]:
            if doc["type"] == CLOSURE_TYPE and dates.parse(doc["listed_date"]):
                c = dates.parse(doc["listed_date"])
                closure = max(closure, c) if closure else c
                continue
            label = is_cert_label(doc)
            eff, via = None, None
            if label == "exact" and dates.parse(doc["listed_date"]):
                eff, via = dates.parse(doc["listed_date"]), "listing"
            elif label == "near" or (label == "exact" and not dates.parse(doc["listed_date"])):
                reader_used = True
                text = portal.read_document(key, doc["doc_id"])
                ans = reader.read(doc["doc_id"], text)
                ok, why = R.validate(ans, text)
                lk["reader"].append({"doc_id": doc["doc_id"], "answer": ans, "accepted": ok, "why": why})
                if ok:
                    eff, via = dates.parse(ans["effective_date"]), "reader"
                else:
                    reader_failed = why
            if eff:
                latest_any_cert = max(latest_any_cert, eff) if latest_any_cert else eff
                if best is None or eff > best[0]:
                    best = (eff, via, doc["doc_id"])

        # ---- decide: exactly one outcome per row --------------------------------------
        if closure and (latest_any_cert is None or closure > latest_any_cert) \
                and not active_again(row, closure, dates.parse(page["last_activity"])):
            writes.append({"board": row.board, "row_id": row.row_id, "row": row.link, "field": "Status",
                           "old": row.v["Status"], "new": "Closed", "lookup": lid,
                           "basis": {"doc_id": next(d["doc_id"] for d in page["listing"]
                                                    if d["type"] == CLOSURE_TYPE), "via": "listing"}})
            resets.append(row.link)
            finish("CLOSED")
            continue
        if best:
            new_exp = best[0] + dt.timedelta(days=S["validity_days"])
            floor = max(row.expires or dt.date.min, run_date)
            if new_exp > floor:                  # never move a date earlier, never write a stale one
                basis = {"doc_id": best[2], "via": best[1], "effective": str(best[0])}
                for field, old, new in (("Certificate expires", row.v["Certificate expires"], str(new_exp)),
                                        ("On file", row.v["On file"], "yes"),
                                        ("Notes", row.v["Notes"],
                                         (row.v["Notes"] + "\n" if row.v["Notes"] else "")
                                         + f"{run_date}: current certificate found ({best[2]})")):
                    writes.append({"board": row.board, "row_id": row.row_id, "row": row.link,
                                   "field": field, "old": old, "new": new, "lookup": lid, "basis": basis})
                resets.append(row.link)
                finish("ON_FILE", best[1])
                continue
        if reader_used:                          # the reader never triggers an email on its own
            finish("UNCLEAR", f"reader:{reader_failed or 'not_current'}")
            continue
        if not row.v["Account rep email"] or not row.v["Owner email"]:
            finish("UNCLEAR", "missing_contact")
            continue
        sent = int(ledger.get(row.link, 0))
        if sent >= S["ceiling"]:
            finish("UNCLEAR", "notice_ceiling_reached")
            continue
        if sent == 0 and new_threads >= S["new_thread_cap"]:
            finish("DEFERRED", "new_thread_cap")      # checked and recorded; email waits a week
            continue
        new_threads += sent == 0
        n = sent + 1
        outbox.append(email(row, n, run_date, S["ceiling"], week))
        finish("NO_DOCUMENT", f"notice_{n}")

    if held_run:
        lookups.append({"lookup": None, "row": None, "error": held_run, "complete": False})

    # ---- write everything; the worker exits here ---------------------------------------
    def jl(name, items):
        (out_dir / name).write_text("".join(json.dumps(x) + "\n" for x in items))
    jl("report.jsonl", report)
    jl("writes.jsonl", writes)
    jl("outbox.jsonl", outbox)
    jl("lookups.jsonl", lookups)
    counts = {o: sum(r["outcome"] == o for r in report) for o in OUTCOMES}
    meta = {"week": week, "run_date": str(run_date), "dry_run": not live, "held": held_run,
            "data_dir": data_dir.as_posix(), "sendlog": (data_dir / "sendlog.json").as_posix(),
            "counts": counts, "rows": len(rows)}
    (out_dir / "run.json").write_text(json.dumps(meta, indent=1) + "\n")
    (out_dir / "summary.md").write_text(summary(meta, report, writes))

    if live:
        T.apply(boards, writes)
        (data_dir / "tracker.json").write_text(json.dumps(boards, indent=1) + "\n")
        for link in resets:
            ledger[link] = 0
        (data_dir / "reminders.json").write_text(json.dumps(ledger, indent=1) + "\n")
    return meta


def email(row: T.Row, n: int, run_date: dt.date, ceiling: int, week: int) -> dict:
    vid = row.vendor_id
    return {
        "row": row.link, "week": week, "notice": n, "new_thread": n == 1,
        "to": row.v["Account rep email"], "cc": [row.v["Owner email"], row.v["Manager email"]],
        "bcc": row.v["Thread address"],
        "subject": f"Certificate of insurance needed for vendor {vid} (notice {n} of {ceiling})",
        "body": (f"Hello,\n\nWe checked the {PORTAL} on {dates.long_form(run_date)} and could not "
                 f"find a current certificate of insurance for vendor {vid}. Please upload one "
                 f"there so the account stays active.\n\nThis is notice {n} of {ceiling}. If you "
                 f"have already uploaded it, reply here and we will look again before the next "
                 f"notice.\n\nVendor compliance, Corvane Property Services"),
    }


def summary(meta: dict, report: list[dict], writes: list[dict]) -> str:
    """Numbers, then only the rows a person must act on - links and reason codes, never names,
    addresses or vendor IDs."""
    c = meta["counts"]
    out = [f"# Week {meta['week']} ({meta['run_date']}) - {'DRY RUN' if meta['dry_run'] else 'live'}", ""]
    if meta["held"]:
        out += [f"Run held: {meta['held']}. Nothing was checked and nobody was emailed.", ""]
    out += [" | ".join(f"{k} {v}" for k, v in c.items()), "", "## For a person", ""]
    people = [r for r in report if r["outcome"] in ("UNCLEAR", "HELD", "DEFERRED")]
    out += [f"- {r['row']} {r['outcome']} {r['reason']}" for r in people] or ["- none"]
    if meta["dry_run"]:
        out += ["", "## Changes a live run would make", ""]
        out += [f"- {w['row']} {w['field']}: {w['old'] or '(blank)'} -> {w['new']}"
                for w in writes if w["field"] != "Notes"] or ["- none"]
    return "\n".join(out) + "\n"
