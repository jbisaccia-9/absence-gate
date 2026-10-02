import json
import shutil

import pytest

from absencegate import counterexamples, gate, orchestrator, seed, worker


def _report(run):
    return [json.loads(x) for x in (run / "report.jsonl").read_text().splitlines()]


def test_every_week_of_the_season_passes_and_sends(season_run):
    root, code, text = season_run
    assert code == 0, text
    assert all("PASS" in line for line in text.splitlines()[1:10])


def test_held_lookups_where_the_document_was_there_got_no_notice(season_run):
    root, _, text = season_run
    wrong = int(text.split("actually had a certificate: ")[1].split()[0])
    assert wrong > 0                       # the seed really does hide documents behind failures
    for run in sorted((root / "runs").glob("week-*")):
        held = {r["row"] for r in _report(run) if r["outcome"] == "HELD"}
        box = [json.loads(x)["row"] for x in (run / "outbox.jsonl").read_text().splitlines()]
        assert not held & set(box)


def test_portal_down_week_checks_nothing_and_emails_nobody(season_run):
    root, _, _ = season_run
    run = root / "runs" / "week-04"
    assert json.loads((run / "run.json").read_text())["held"] == "portal_unreachable"
    assert (run / "outbox.jsonl").read_text() == ""
    assert all(r["outcome"] in ("SKIPPED", "NOT_DUE", "HELD") for r in _report(run))


def test_four_failures_in_a_row_stops_the_lookups(season_run):
    root, _, _ = season_run
    reasons = [r["reason"] for r in _report(root / "runs" / "week-06") if r["outcome"] == "HELD"]
    assert reasons.count("timeout") == 4 and "stopped_after_failures" in reasons


def test_a_vendor_that_never_uploads_gets_six_notices_then_a_person(season_run):
    root, _, _ = season_run
    ledger = json.loads((root / "data" / "reminders.json").read_text())
    last = {r["row"]: r for r in _report(root / "runs" / "week-09")}
    capped = [k for k, r in last.items() if r["reason"] == "notice_ceiling_reached"]
    assert capped and all(ledger[k] == 6 for k in capped)
    assert max(ledger.values()) == 6


def test_the_reader_never_triggers_a_notice(season_run):
    root, _, _ = season_run
    for run in (root / "runs").glob("week-*"):
        lookups = {json.loads(x).get("lookup"): json.loads(x) for x in (run / "lookups.jsonl").read_text().splitlines()}
        for r in _report(run):
            if r["outcome"] == "NO_DOCUMENT":
                assert not lookups[r["lookup"]]["reader"]


@pytest.mark.parametrize("name", sorted(counterexamples.DESCRIPTIONS))
def test_counterexample_is_refused_for_exactly_its_own_rule(tmp_path, name):
    counterexamples.build(tmp_path / "data", tmp_path / "cx")
    v = gate.grade(tmp_path / "cx" / name, mode="send")
    assert v.rules_failed == [name[:2].upper()], v.failures


def test_dry_run_is_the_default_writes_nothing_and_cannot_be_sent(tmp_path):
    seed.write(tmp_path / "d")
    before = (tmp_path / "d" / "tracker.json").read_text()
    meta = worker.run(tmp_path / "d", 1, tmp_path / "run")
    assert meta["dry_run"] and (tmp_path / "d" / "tracker.json").read_text() == before
    assert gate.grade(tmp_path / "run").passed
    code, text = orchestrator.send(tmp_path / "run")
    assert code == 1 and "G7" in text and not (tmp_path / "d" / "mailbox").exists()


def test_sending_twice_sends_once(tmp_path):
    seed.write(tmp_path / "d")
    worker.run(tmp_path / "d", 1, tmp_path / "run", live=True)
    assert orchestrator.send(tmp_path / "run")[0] == 0
    code, text = orchestrator.send(tmp_path / "run")
    assert code == 1 and "G7" in text
    assert len(json.loads((tmp_path / "d" / "sendlog.json").read_text())) == 10


def test_an_unread_near_miss_label_cannot_produce_a_notice(tmp_path, monkeypatch):
    """The hole the first full season exposed: 'cert of ins' fell through the label check,
    so a vendor with a valid certificate got notices and the gate passed it."""
    seed.write(tmp_path / "d")
    original = worker.is_cert_label
    monkeypatch.setattr(worker, "is_cert_label",
                        lambda d: "" if original(d) == "near" and "insur" not in " ".join(
                            [d["type"], d["notes"], d["file_name"]]).lower() else original(d))
    worker.run(tmp_path / "d", 1, tmp_path / "run", settings={"new_thread_cap": 50})
    monkeypatch.setattr(worker, "is_cert_label", original)   # the gate grades with the real rule
    v = gate.grade(tmp_path / "run")
    assert "G3" in v.rules_failed and "never read" in v.failures["G3"][0]


def test_a_date_is_never_moved_earlier(tmp_path):
    seed.write(tmp_path / "d")
    worker.run(tmp_path / "d", 1, tmp_path / "run")
    w = [json.loads(x) for x in (tmp_path / "run" / "writes.jsonl").read_text().splitlines()]
    exp = next(x for x in w if x["field"] == "Certificate expires" and x["basis"]["via"] == "listing")
    rows = (tmp_path / "run" / "writes.jsonl").read_text().replace(exp["new"], "2026-10-06")
    (tmp_path / "run" / "writes.jsonl").write_text(rows)
    assert "G2" in gate.grade(tmp_path / "run").rules_failed


def test_an_interrupted_send_is_refused_on_plain_retry_and_finished_by_resume(tmp_path):
    seed.write(tmp_path / "d")
    worker.run(tmp_path / "d", 1, tmp_path / "run", live=True)
    box = [json.loads(x) for x in (tmp_path / "run" / "outbox.jsonl").read_text().splitlines()]
    log = {gate.send_key(m): {"to": m["to"], "week": 1} for m in box[:3]}   # crashed after three
    (tmp_path / "d" / "sendlog.json").write_text(json.dumps(log))
    code, text = orchestrator.send(tmp_path / "run")
    assert code == 1 and "G7" in text
    code, text = orchestrator.send(tmp_path / "run", resume=True)
    assert code == 0 and "sent 7" in text and "skipped 3" in text
    assert len(json.loads((tmp_path / "d" / "sendlog.json").read_text())) == 10


# ---- one test per lesson from the first build ---------------------------------------------

def test_lesson_older_portals_are_rarely_one_page(tmp_path, monkeypatch):
    """A worker that reads only the first page of documents misses certificates on page two
    and sends notices it shouldn't. The gate counts the pages the portal says it served."""
    from absencegate import portal
    seed.write(tmp_path / "d")
    real_open = portal.MockPortal.open
    monkeypatch.setattr(portal.MockPortal, "open", lambda self, key: {**real_open(self, key), "pages": 1})
    worker.run(tmp_path / "d", 1, tmp_path / "run", settings={"new_thread_cap": 50})
    v = gate.grade(tmp_path / "run")
    assert v.rules_failed == ["G3"]
    assert any("of 2 document pages" in f or "was on file" in f for f in v.failures["G3"])


def test_lesson_every_failure_names_its_step(season_run):
    root, _, _ = season_run
    held = [r for r in _report(root / "runs" / "week-01") if r["outcome"] == "HELD"]
    assert {r["step"] for r in held} >= {"documents_page_1", "documents_page_2", "record_page"}
    lookups = [json.loads(x) for x in (root / "runs" / "week-01" / "lookups.jsonl").read_text().splitlines()]
    errors = [l["error"] for l in lookups if l.get("error")]
    assert errors and all(e.split(":")[0].startswith(("documents_page_", "record_page")) for e in errors)


def test_lesson_a_record_that_closed_and_reopened_is_not_closed_again(season_run):
    root, _, _ = season_run
    from absencegate import tracker
    rows = tracker.current_cycle(tracker.rows(tracker.load(root / "runs" / "week-01" / "inputs" / "tracker.json")))
    reopened = [r for r in rows if r.v["Cycle start"] == str(seed.week_date(1) - __import__("datetime").timedelta(days=6))]
    assert reopened
    out = {r["row"]: r for r in _report(root / "runs" / "week-01")}
    assert all(out[r.link]["outcome"] in ("NO_DOCUMENT", "DEFERRED") for r in reopened)


def test_lesson_mark_sent_only_after_it_is_sent(tmp_path, monkeypatch):
    seed.write(tmp_path / "d")
    worker.run(tmp_path / "d", 1, tmp_path / "run", live=True)
    real, calls = orchestrator.deliver, {"n": 0}

    def flaky(mailbox, m):
        calls["n"] += 1
        if calls["n"] == 4:
            raise ConnectionError("mail service reset the connection")
        real(mailbox, m)

    monkeypatch.setattr(orchestrator, "deliver", flaky)
    code, text = orchestrator.send(tmp_path / "run")
    assert code == 1 and "delivery failed at notice 4" in text
    assert len(json.loads((tmp_path / "d" / "sendlog.json").read_text())) == 3   # not 4, not 10
    code, text = orchestrator.send(tmp_path / "run", resume=True)
    assert code == 0 and "sent 7" in text and "skipped 3" in text


def test_lesson_dry_run_applies_the_same_caps_as_live(tmp_path):
    for mode in ("dry", "live"):
        seed.write(tmp_path / mode)
        worker.run(tmp_path / mode, 1, tmp_path / f"run-{mode}", live=mode == "live")
    for f in ("report.jsonl", "outbox.jsonl", "writes.jsonl"):
        assert (tmp_path / "run-dry" / f).read_text().replace("dry", "X") == \
               (tmp_path / "run-live" / f).read_text().replace("live", "X")
    deferred = [r for r in _report(tmp_path / "run-dry") if r["outcome"] == "DEFERRED"]
    assert deferred                        # the cap really binds in week 1


def test_contract_worker_files_are_what_the_orchestrator_and_gate_read(tmp_path):
    seed.write(tmp_path / "d")
    worker.run(tmp_path / "d", 1, tmp_path / "run")
    for m in (json.loads(x) for x in (tmp_path / "run" / "outbox.jsonl").read_text().splitlines()):
        assert {"row", "week", "notice", "new_thread", "to", "cc", "bcc", "subject", "body"} <= set(m)
    for r in _report(tmp_path / "run"):
        assert {"row", "outcome", "reason"} <= set(r)
    meta = json.loads((tmp_path / "run" / "run.json").read_text())
    assert {"week", "dry_run", "held", "data_dir", "sendlog", "counts"} <= set(meta)
