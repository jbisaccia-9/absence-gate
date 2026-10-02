"""The orchestrator owns the schedule and the mailbox. It re-grades the run with G7 on,
refuses the whole run if anything fails, and sends each queued message exactly once."""
from __future__ import annotations

import json
from pathlib import Path

from . import gate


def send(run_dir: Path, resume: bool = False) -> tuple[int, str]:
    """A plain send refuses any run the send log has already touched (G7). `resume` is the
    deliberate way to finish an interrupted run: G1-G6 still apply, a dry run is still
    refused, and every notice the log already holds is skipped rather than resent."""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text())
    v = gate.grade(run_dir, mode="build" if resume else "send")
    if resume and meta["dry_run"]:
        v.fail("G7", "this is a dry run; its outbox is never sent")
    if not v.passed:
        return 1, v.line()
    data = Path(meta["data_dir"])
    log_path, ledger_path = Path(meta["sendlog"]), data / "reminders.json"
    mailbox = data / "mailbox" / f"week-{meta['week']:02d}"
    mailbox.mkdir(parents=True, exist_ok=True)
    sent = skipped = 0
    for line in (run_dir / "outbox.jsonl").read_text().splitlines():
        m = json.loads(line)
        # Re-read both files per message: a crash at message 40 must not resend 1-39.
        log = json.loads(log_path.read_text())
        key = gate.send_key(m)
        if key in log:
            skipped += 1
            continue
        try:
            deliver(mailbox, m)
        except Exception as e:                  # noqa: BLE001 - any transport failure
            # Logged only after a successful send, so this notice stays unsent and
            # `send --resume` hands it back.
            return 1, (f"delivery failed at notice {sent + skipped + 1} ({type(e).__name__}); "
                       f"{sent} sent and logged this attempt - finish with send --resume")
        log[key] = {"to": m["to"], "week": m["week"]}
        log_path.write_text(json.dumps(log, indent=1) + "\n")
        ledger = json.loads(ledger_path.read_text())
        ledger[m["row"]] = m["notice"]
        ledger_path.write_text(json.dumps(ledger, indent=1) + "\n")
        sent += 1
    (mailbox / "summary-to-owners.md").write_text((run_dir / "summary.md").read_text())
    return 0, f"sent {sent} notice(s) and 1 summary" + (f", skipped {skipped} already sent" if skipped else "")


def deliver(mailbox: Path, m: dict) -> None:
    """The one function to swap for a real mail API."""
    (mailbox / f"{m['row'].split('/')[-1]}-n{m['notice']}.json").write_text(json.dumps(m, indent=1))
