"""Deterministic synthetic world. Corvane Property Services, the Tallgrass Vendor Exchange and
every vendor, person, address and document below are fictional.

The shape: a property manager keeps a tracker of contracted vendors. Each vendor must keep a
current certificate of insurance on file in a third-party procurement portal that has no API,
shows documents in an inconsistent way, and sometimes simply doesn't load. Every scenario
below exists because a weekly check-then-chase job can get it wrong quietly.
"""
from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

from .dates import long_form

WEEK1 = dt.date(2026, 10, 5)
WEEKS = 9
COMPANY_DOMAIN = "corvane.example"
PORTAL = "Tallgrass Vendor Exchange"

PRE = ["Bramblecrest", "Ostrander", "Vellmore", "Quillon", "Harrowgate", "Tamsin", "Larchfield",
       "Pembrook", "Corrigan", "Ashgrove", "Dunleavy", "Marrowind", "Fenhallow", "Gilcrest",
       "Wexbridge", "Calderon", "Ivorydale", "Rookwood", "Saltmarsh", "Thistledown"]
TRADE = ["Glazing", "Roofing", "Elevator", "Mechanical", "Paving", "Grounds", "Electric",
         "Plumbing", "Fire Systems", "Facility Care", "Masonry", "Door & Lock"]
SUFFIX = ["Co.", "LLC", "Group", "Works", "Partners"]
FIRST = ["Orla", "Benedikt", "Yusra", "Caius", "Mireille", "Tavish", "Ottilie", "Ramon",
         "Saskia", "Leopold", "Zainab", "Ferris", "Ingrid", "Matthias", "Noor", "Bastien"]
LAST = ["Achterberg", "Bellamy", "Cuthbert", "Delacroix-Hale", "Ellingsen", "Fairweather",
        "Grisham-Ode", "Holloway", "Ivanescu", "Juhl", "Kettering", "Lowenthal"]

CERT_TYPES = ["Certificate of Insurance", "COI - General Liability"]          # exact phrases only
LOOKALIKES = ["Certificate of Insurance Request Form", "Sample Certificate of Insurance",
              "Certificate of Insurance (Expired Policy)"]                     # always refused
NEAR = ["Insurance Cert - renewal", "GL insurance certificate", "cert of ins"]  # reader decides
CLOSURE_TYPE = "Vendor Offboarding Notice"


def week_date(week: int) -> dt.date:
    return WEEK1 + dt.timedelta(days=7 * (week - 1))


def _doc(doc_id, dtype, listed, notes="", file_name=None, visible_from=1, text=None):
    return {"doc_id": doc_id, "type": dtype, "notes": notes,
            "file_name": file_name or f"{doc_id}.pdf",
            "listed_date": listed, "visible_from_week": visible_from,
            "text": text or ""}


def _cert_text(vendor: str, effective: dt.date) -> str:
    return (f"CERTIFICATE OF LIABILITY INSURANCE\nInsured: {vendor}\n"
            f"Certificate holder: Corvane Property Services\n"
            f"Policy period begins {long_form(effective)} and runs twelve months.\n"
            f"Coverage: commercial general liability, each occurrence limit as scheduled.\n")


def build(seed: int = 4207) -> dict:
    rng = random.Random(seed)
    run1 = week_date(1)
    names = [f"{p} {t} {s}" for p in PRE for t in TRADE for s in SUFFIX]
    rng.shuffle(names)
    people = [(f, l) for f in FIRST for l in LAST]
    rng.shuffle(people)

    # (scenario, count). Order matters only for determinism.
    plan = [("current", 46), ("on_file", 9), ("late_upload:2", 2), ("late_upload:3", 2),
            ("late_upload:5", 2), ("never", 3), ("lookalike_only", 2), ("stale_cert", 1),
            ("reader_ok", 2), ("reader_low_conf", 1), ("reader_ungrounded", 1),
            ("no_listed_date", 1), ("closed", 2), ("closed_but_renewing", 1),
            ("name_fallback", 1), ("two_matches", 1), ("id_mismatch", 1), ("no_contact", 1),
            ("flaky", 3), ("unknown_prompt", 1), ("cert_on_page_two", 2), ("page_two_flaky", 1),
            ("closed_then_reopened", 1),
            ("skip_archived", 3), ("skip_closed", 3), ("skip_exempt", 2)]

    vendors, n = [], 0
    for scenario, count in plan:
        for _ in range(count):
            vid = f"V-{30117 + 7 * n}"
            first, last = people[n]
            name = names[n]
            slug = name.split()[0].lower()
            vendors.append({
                "vendor_id": vid, "name": name, "scenario": scenario,
                "board": "east" if n % 2 == 0 else "west",
                "rep": f"{first} {last}",
                "rep_email": "" if scenario == "no_contact" else f"{first[0]}{last}@{slug}-{n}.example".lower().replace(" ", ""),
                "owner_email": f"owner{n % 6 + 1}@{COMPANY_DOMAIN}",
                "manager_email": f"mgr{n % 3 + 1}@{COMPANY_DOMAIN}",
            })
            n += 1

    boards = {"east": {"columns": {}, "rows": []}, "west": {"columns": {}, "rows": []}}
    titles = ["Vendor ID", "Vendor", "Cycle start", "Certificate expires", "On file", "Status",
              "Group", "Scope", "Renewal pending", "Hold", "Account rep email", "Owner email",
              "Manager email", "Thread address", "Notes"]
    for b, board in boards.items():
        # Same field, different internal id on each board: columns must be found by title.
        board["columns"] = {f"c_{b[0]}{rng.randrange(16**4):04x}": t for t in titles}
    col = {b: {t: cid for cid, t in boards[b]["columns"].items()} for b in boards}

    portal = {"vendors": {}, "down_weeks": [4], "streak_week": 6, "streak_len": 4}
    reader = {}
    row_n = 0

    def add_row(v, cycle_start, expires, status="Active", group="Active vendors", scope="Required",
                renewing="", hold=""):
        nonlocal row_n
        b = v["board"]
        vals = {"Vendor ID": v["vendor_id"], "Vendor": v["name"], "Cycle start": str(cycle_start),
                "Certificate expires": str(expires) if expires else "", "On file": "",
                "Status": status, "Group": group, "Scope": scope, "Renewal pending": renewing,
                "Hold": hold, "Account rep email": v["rep_email"], "Owner email": v["owner_email"],
                "Manager email": v["manager_email"],
                "Thread address": f"pulse+{b}-{row_n:04d}@{COMPANY_DOMAIN}", "Notes": ""}
        boards[b]["rows"].append({"row_id": f"r{row_n:04d}",
                                  "values": {col[b][t]: x for t, x in vals.items()}})
        row_n += 1

    for i, v in enumerate(vendors):
        s = v["scenario"]
        vid, name = v["vendor_id"], v["name"]
        docs, rec = [], {"name": name, "portal_id": vid, "timeout_weeks": [], "prompt": None,
                         "last_activity": str(run1 - dt.timedelta(days=60))}
        cycle = run1 - dt.timedelta(days=rng.randint(200, 330))
        due_exp = rng.choice([None, run1 - dt.timedelta(days=rng.randint(3, 40)),
                              run1 + dt.timedelta(days=rng.randint(4, 40))])
        if s == "closed_then_reopened":   # closed last cycle, reopened this one, nothing on file yet
            add_row(v, cycle - dt.timedelta(days=365), cycle - dt.timedelta(days=2), status="Closed")
            cycle = run1 - dt.timedelta(days=6)
        elif i % 9 == 0:   # an older cycle row for the same vendor that must be ignored
            add_row(v, cycle - dt.timedelta(days=365), cycle - dt.timedelta(days=2))

        def cert(doc_id, eff, dtype="Certificate of Insurance", visible_from=1, listed=True):
            docs.append(_doc(doc_id, dtype, str(eff) if listed else "", visible_from=visible_from,
                             text=_cert_text(name, eff)))

        if s == "current":
            add_row(v, cycle, run1 + dt.timedelta(days=rng.randint(60, 300)))
        elif s.startswith("skip_"):
            kind = s.split("_")[1]
            add_row(v, cycle, due_exp, status="Closed" if kind == "closed" else "Active",
                    group="Archive 2025" if kind == "archived" else "Active vendors",
                    scope="Exempt" if kind == "exempt" else "Required")
        else:
            add_row(v, cycle, due_exp, renewing="yes" if s == "closed_but_renewing" else "")
            eff = run1 - dt.timedelta(days=rng.randint(2, 20))
            did = f"D{50000 + 13 * i}"
            if s in ("on_file", "name_fallback", "two_matches", "id_mismatch", "unknown_prompt"):
                cert(did, eff, dtype=rng.choice(CERT_TYPES))
            elif s.startswith("late_upload"):
                cert(did, eff + dt.timedelta(days=7 * int(s.split(":")[1])),
                     visible_from=int(s.split(":")[1]))
            elif s == "lookalike_only":
                docs.append(_doc(did, rng.choice(LOOKALIKES), str(eff)))
            elif s == "stale_cert":                      # a real cert, but last year's
                cert(did, run1 - dt.timedelta(days=400))
            elif s in ("reader_ok", "reader_low_conf", "reader_ungrounded"):
                docs.append(_doc(did, rng.choice(NEAR), str(eff), text=_cert_text(name, eff)))
                good = {"is_target_document": True, "effective_date": str(eff),
                        "confidence": 0.93,
                        "evidence": f"Policy period begins {long_form(eff)}",
                        "model": "doc-reader-small", "prompt_version": "r3"}
                if s == "reader_low_conf":
                    good["confidence"] = 0.61
                if s == "reader_ungrounded":   # plausible, well-formed, and not in the document
                    good["evidence"] = f"Coverage effective {long_form(eff)} through renewal"
                reader[did] = good
            elif s == "no_listed_date":
                cert(did, eff, listed=False)
                reader[did] = {"is_target_document": True, "effective_date": str(eff),
                               "confidence": 0.97,
                               "evidence": f"Policy period begins {long_form(eff)}",
                               "model": "doc-reader-small", "prompt_version": "r3"}
            elif s == "closed":
                old = run1 - dt.timedelta(days=300)
                cert(did, old)
                docs.append(_doc(f"D{50001 + 13 * i}", CLOSURE_TYPE, str(run1 - dt.timedelta(days=9))))
            elif s == "closed_but_renewing":          # closure is ignored: tracker says renewing
                docs.append(_doc(f"D{50001 + 13 * i}", CLOSURE_TYPE, str(run1 - dt.timedelta(days=9))))
                cert(did, eff)
            elif s in ("cert_on_page_two", "page_two_flaky"):
                for j, t in enumerate(["W-9 Request", "Safety Plan", "Rate Sheet", "Signed MSA", "Lien Waiver"]):
                    docs.append(_doc(f"D{60000 + 13 * i + j}", t, str(eff - dt.timedelta(days=30 + j))))
                cert(did, eff)                     # sixth document: page two
                if s == "page_two_flaky":
                    rec["page_timeout_weeks"] = [1]
            elif s == "closed_then_reopened":
                docs.append(_doc(f"D{50001 + 13 * i}", CLOSURE_TYPE, str(run1 - dt.timedelta(days=40))))
            elif s == "flaky":
                cert(did, eff + dt.timedelta(days=14), visible_from=3)   # document DOES arrive
                rec["timeout_weeks"] = [1, 2]
            # "never", "no_contact": nothing on file, ever.

            if s == "name_fallback":
                rec["portal_id"] = vid.replace("-", "")           # portal stores it differently
            if s == "two_matches":
                rec["portal_id"] = vid.replace("-", "")
                portal["vendors"][f"{vid}-dup"] = {"name": name, "portal_id": "V99999",
                                                   "documents": [], "timeout_weeks": [],
                                                   "prompt": None, "last_activity": rec["last_activity"]}
            if s == "id_mismatch":
                rec["shown_id"] = "V-39999"
            if s == "unknown_prompt":
                rec["prompt"] = "Update your security questions to continue"
        rec["documents"] = docs
        if i % 4 == 1 and not rec["prompt"]:
            rec["prompt"] = "Session notice: continue to vendor record"   # approved prompt
        portal["vendors"][vid] = rec

    return {"boards": boards, "portal": portal, "reader": reader}


def write(data_dir: Path, seed: int = 4207) -> Path:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    w = build(seed)
    (data_dir / "tracker.json").write_text(json.dumps(w["boards"], indent=1) + "\n")
    (data_dir / "portal.json").write_text(json.dumps(w["portal"], indent=1) + "\n")
    (data_dir / "reader_answers.json").write_text(json.dumps(w["reader"], indent=1) + "\n")
    (data_dir / "reminders.json").write_text("{}\n")
    (data_dir / "sendlog.json").write_text("{}\n")
    return data_dir
