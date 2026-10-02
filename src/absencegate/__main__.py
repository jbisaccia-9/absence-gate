from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import counterexamples, gate, orchestrator, season, seed, worker


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="absencegate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("seed", help="write the synthetic tracker, portal and recorded reader answers")
    a.add_argument("data")
    a = sub.add_parser("run", help="one weekly run; DRY RUN unless --live")
    a.add_argument("data"); a.add_argument("--week", type=int, default=1)
    a.add_argument("--out", default="out/run"); a.add_argument("--live", action="store_true")
    a = sub.add_parser("send", help="orchestrator: re-grade with G7, send each notice once")
    a.add_argument("run"); a.add_argument("--resume", action="store_true",
                                          help="finish an interrupted run, skipping notices already sent")
    a = sub.add_parser("check-dir", help="grade every run in a directory; exit 1 if any is refused")
    a.add_argument("dir"); a.add_argument("--send", action="store_true")
    a = sub.add_parser("season", help="seed, then run, grade and send every week of the season")
    a.add_argument("data"); a.add_argument("--out", default="out/season")
    a = sub.add_parser("counterexamples", help="build the runs that must be refused")
    a.add_argument("out"); a.add_argument("--data", default="out/cx-data")
    args = ap.parse_args(argv)

    if args.cmd == "seed":
        print(f"wrote {seed.write(Path(args.data))}")
        return 0
    if args.cmd == "run":
        meta = worker.run(Path(args.data), args.week, Path(args.out), live=args.live)
        v = gate.grade(Path(args.out))
        print(Path(args.out, "summary.md").read_text() + "\n" + v.line())
        return 0 if v.passed else 1
    if args.cmd == "send":
        code, text = orchestrator.send(Path(args.run), resume=args.resume)
    elif args.cmd == "check-dir":
        vs = gate.check_dir(Path(args.dir), "send" if args.send else "build")
        bad = sum(not v.passed for v in vs)
        text = "\n".join(v.line() for v in vs) + f"\n\n{len(vs) - bad} pass, {bad} refused"
        code = 1 if bad or not vs else 0
    elif args.cmd == "season":
        code, text = season.run(Path(args.data), Path(args.out))
    else:
        names = counterexamples.build(Path(args.data), Path(args.out))
        text = "\n".join(f"{n:<26} {counterexamples.DESCRIPTIONS[n]}" for n in names)
        code = 0
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
