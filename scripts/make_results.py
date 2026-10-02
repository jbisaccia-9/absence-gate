"""Regenerate RESULTS.md from real command output. Run from the repo root."""
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

STEPS = [
    ("Unit tests", "python -m pytest -q", 0),
    ("The season: nine weekly runs, each live, graded, then sent", "python -m absencegate season data --out out/season", 0),
    ("A dry run (the default)", "python -m absencegate seed dry && python -m absencegate run dry --week 1 --out out/dry", 0),
    ("A dry run's outbox can never be sent", "python -m absencegate send out/dry", 1),
    ("Build the counterexamples", "python -m absencegate counterexamples out/cx --data out/cx-data", 0),
    ("Gate refuses every counterexample, each for its own rule", "python -m absencegate check-dir out/cx --send", 1),
]
for d in ("out", "data", "dry"):
    shutil.rmtree(d, ignore_errors=True)
out = [f"# Results\n\nGenerated {datetime.date.today()} by `scripts/make_results.py` \u2014 every block below is captured command output, not prose.\n"]
ok_all = True
for title, cmd, want in STEPS:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    good = (r.returncode == 0) if want == 0 else (r.returncode != 0)
    ok_all &= good
    body = (r.stdout + r.stderr).strip()
    if "pytest" in cmd:
        body = "\n".join(l for l in body.splitlines() if not l.startswith("=") or "passed" in l)
    exp = "exit 0" if want == 0 else "expected non-zero exit"
    out.append(f"## {title}\n\n`{cmd}` \u2014 {exp}, {'OK' if good else 'UNEXPECTED'}\n\n```\n{body}\n```\n")
Path("RESULTS.md").write_text("\n".join(out), encoding="utf-8")
print("wrote RESULTS.md", "OK" if ok_all else "WITH UNEXPECTED RESULTS")
sys.exit(0 if ok_all else 1)
