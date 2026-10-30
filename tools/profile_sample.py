#!/usr/bin/env python3
"""Standalone profiler: CSV in, aggregate-only report out. No ledger is touched.

This is the quickest way to look at an export before committing it to the ledger:

  python3 tools/profile_sample.py EXPORT.csv [--since Y-M-D] [--until Y-M-D]
        [--accounts "amex,chase"] [--sign auto|neg-out|pos-out]
        [--map date=Date,amount=Amount,merchant=Description,category=Category,account=Account]
        [--out reports/] [--quiet]
  python3 tools/profile_sample.py --example example.csv  # create and profile example transactions

Same engine as `python3 -m mint profile`; see mint/profile.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from mint.importers import csv_to_memory_rows  # noqa: E402
from mint.profile import profile, render_md  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--example", "--demo", dest="demo", metavar="PATH")
    ap.add_argument("--since", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    ap.add_argument("--until", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    ap.add_argument("--accounts")
    ap.add_argument("--sign", choices=["auto", "neg-out", "pos-out"], default="auto")
    ap.add_argument("--map")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.demo:
        from mint.demo import write_demo
        print(f"wrote {write_demo(args.demo)} example rows to {args.demo}", file=sys.stderr)
        args.csv = args.demo
    if not args.csv:
        ap.error("give a CSV path or --example PATH")
    overrides = {}
    if args.map:
        for part in args.map.split(","):
            role, col = part.split("=", 1)
            overrides[role.strip().lower()] = col.strip()
    filters = [s.strip() for s in args.accounts.split(",")] if args.accounts else []
    try:
        rows, meta = csv_to_memory_rows(args.csv, overrides, args.sign, args.since, args.until, filters)
    except ValueError as e:
        sys.exit(str(e))
    p = profile(rows, args.since, args.until)
    meta.update({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "source": os.path.basename(args.csv)})
    md = render_md(p, meta)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "profile.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(args.out, "profile.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "profile": p}, f, indent=2, default=str)
    if not args.quiet:
        print(md)
    print(f"\nwrote {args.out}/profile.md and profile.json. columns={meta['columns']} skipped={meta['skipped']}", file=sys.stderr)


if __name__ == "__main__":
    main()
