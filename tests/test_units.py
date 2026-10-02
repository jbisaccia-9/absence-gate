import datetime as dt

from absencegate import dates, reader, seed, tracker, worker


def test_columns_are_found_by_title_not_id():
    w = seed.build()
    east, west = w["boards"]["east"]["columns"], w["boards"]["west"]["columns"]
    assert set(east.values()) == set(west.values()) and not set(east) & set(west)
    assert all(r.vendor_id.startswith("V-") for r in tracker.rows(w["boards"]))


def test_only_the_current_cycle_is_worked():
    rows = tracker.rows(seed.build()["boards"])
    cur = tracker.current_cycle(rows)
    assert len(cur) < len(rows) and len({r.vendor_id for r in cur}) == len(cur)


def test_labels_exact_beats_near_and_lookalikes_are_always_refused():
    d = lambda t, notes="", fn="x.pdf": {"type": t, "notes": notes, "file_name": fn}
    assert worker.is_cert_label(d("Certificate of Insurance")) == "exact"
    assert worker.is_cert_label(d("Other", fn="COI - General Liability.pdf")) == "exact"
    assert worker.is_cert_label(d("Certificate of Insurance Request Form")) == "lookalike"
    assert worker.is_cert_label(d("Certificate of Insurance", notes="Sample Certificate of Insurance")) == "lookalike"
    assert worker.is_cert_label(d("cert of ins")) == "near"
    assert worker.is_cert_label(d("W-9 form")) == ""


def test_reader_answers_are_accepted_only_when_grounded():
    text = "Policy period begins October 1, 2026 and runs twelve months."
    ok = {"is_target_document": True, "effective_date": "2026-10-01", "confidence": 0.9,
          "evidence": "Policy period begins October 1, 2026"}
    assert reader.validate(ok, text) == (True, "ok")
    assert reader.validate({**ok, "confidence": 0.84}, text)[1] == "low_confidence"
    assert reader.validate({**ok, "evidence": "Coverage effective October 1, 2026"}, text)[1] == "evidence_not_in_document"
    assert reader.validate({**ok, "effective_date": "2026-10-02"}, text)[1] == "evidence_does_not_state_date"
    assert reader.validate({**ok, "effective_date": "soon"}, text)[1] == "date_unparseable"
    assert reader.validate({**ok, "is_target_document": False}, text)[1] == "not_target"
    assert reader.validate({"evidence": "x"}, text)[1] == "schema"


def test_missing_or_unreadable_expiry_means_due():
    rows = tracker.current_cycle(tracker.rows(seed.build()["boards"]))
    blank = next(r for r in rows if not r.v["Certificate expires"] and worker.skip_reason(r) is None)
    assert worker.is_due(blank, dt.date(2026, 10, 5), 45)
    assert dates.parse("10/05/2026") is None and dates.parse("October 5, 2026") == dt.date(2026, 10, 5)
