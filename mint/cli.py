"""Command line: python3 -m mint <command>."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

from . import ledger
from .character import build_sheet, compare, render_scoreboard, render_sheet
from .profile import profile, render_md


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _overrides(m):
    out = {}
    if m:
        for part in m.split(","):
            if "=" not in part:
                raise SystemExit(f"--map entry '{part}' is not role=Column")
            role, col = part.split("=", 1)
            out[role.strip().lower()] = col.strip()
    return out


def _filters(s):
    return [x.strip() for x in s.split(",")] if s else []


def _window(args, con):
    """Resolve since/until; default to full ledger range."""
    since, until = getattr(args, "since", None), getattr(args, "until", None)
    if getattr(args, "days", None):
        until = until or date.today()
        since = until - timedelta(days=args.days - 1)
    return since, until


def cmd_init(args):
    cfg = ledger.init_home()
    print(f"mint home: {ledger.mint_home()}")
    print(f"ledger:    {ledger.db_path()}")
    print("ingest token stored in config.json (used by `mint serve` and the iPhone Shortcut)")


def cmd_demo(args):
    from .demo import write_demo
    n = write_demo(args.path, days=args.days)
    print(f"wrote {n} example rows to {args.path}")


def cmd_import_csv(args):
    from .importers import import_csv
    ledger.init_home()
    with ledger.connect() as con:
        res = import_csv(con, args.path, source_name=args.source, overrides=_overrides(args.map), sign=args.sign,
                         since=args.since, until=args.until, account_filters=_filters(args.accounts), keep_raw=not args.no_raw)
    print(json.dumps(res, indent=2, default=str))


def cmd_profile(args):
    with ledger.connect() as con:
        since, until = _window(args, con)
        rows = ledger.fetch_rows(con, since, until, _filters(args.accounts))
    if not rows:
        raise SystemExit("no rows in window")
    p = profile(rows, since, until)
    meta = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "source": "ledger", "sign_note": ""}
    md = render_md(p, meta)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "profile.md"), "w") as f:
            f.write(md)
        with open(os.path.join(args.out, "profile.json"), "w") as f:
            json.dump({"meta": meta, "profile": p}, f, indent=2, default=str)
        print(f"wrote {args.out}/profile.md and profile.json", file=sys.stderr)
    if args.json:
        print(json.dumps(p, indent=2, default=str))
    elif not args.quiet:
        print(md)


def _engine_inputs(con):
    cfg = ledger.load_config()
    return dict(cfg.get("engine_inputs", {}))


def cmd_character(args):
    with ledger.connect() as con:
        if args.action == "show":
            ch = ledger.load_character(con, args.name)
            if not ch:
                raise SystemExit("no character built yet. Run: mint character build --name 'Year One'")
            print(render_sheet(ch["sheet"]) if not args.json else json.dumps(ch, indent=2))
            return
        since, until = _window(args, con)
        rows = ledger.fetch_rows(con, since, until, _filters(args.accounts))
        if not rows:
            raise SystemExit("no rows in window")
        p = profile(rows, since, until)
        days = p["coverage"]["days"]
        sheet = build_sheet(p, days, _engine_inputs(con), name=args.name)
        sheet["profile_window"] = {"since": p["coverage"]["start"], "until": p["coverage"]["end"]}
        ledger.save_character(con, args.name, _d(p["coverage"]["start"]), _d(p["coverage"]["end"]), sheet)
        con.commit()
    print(render_sheet(sheet) if not args.json else json.dumps(sheet, indent=2))


def week_text(days: int = 7, vs: str | None = None, until: date | None = None) -> str:
    with ledger.connect() as con:
        rival = ledger.load_character(con, vs)
        until = until or date.today()
        since = until - timedelta(days=days - 1)
        rows = ledger.fetch_rows(con, since, until)
    if not rows:
        return f"No transactions between {since} and {until}."
    p = profile(rows, since, until)
    ref_income, ref_bills = None, None
    if rival:
        ref_income = rival["sheet"]["metrics"].get("income_monthly")
    if days < 28:
        # Subscriptions do not change week to week: measure them over a longer trailing window.
        with ledger.connect() as con:
            long_rows = ledger.fetch_rows(con, until - timedelta(days=99), until)
        if long_rows:
            ref_bills = profile(long_rows, until - timedelta(days=99), until).get("bills_monthly_ex_fixed", 0.0)
    current = build_sheet(p, days, name="You", reference_income_monthly=ref_income, bills_monthly_ex_fixed=ref_bills)
    label = f"Last {days} days ({since} to {until})"
    if not rival:
        return render_sheet(current) + "\n(no rival built yet: mint character build --name 'Year One')"
    cmp = compare(current, rival["sheet"])
    return render_scoreboard(cmp, current, rival["name"], label)


def cmd_week(args):
    print(week_text(args.days, args.vs, args.until))


def cmd_status(args):
    with ledger.connect() as con:
        st = ledger.status(con)
    if args.json:
        print(json.dumps(st, indent=2, default=str))
        return
    tx = st["transactions"]
    print(f"home: {st['home']}")
    print(f"transactions: {tx['n']} ({tx['first']} to {tx['last']})")
    for s in st["by_source"]:
        print(f"  source {s['source']}: {s['n']} rows, last import {s['last_import']}")
    print("accounts:")
    for a in st["by_account"]:
        print(f"  {a['name']} [{a['kind']}]: {a['n']} rows, last {a['last']}")
    if st["balances"]:
        print("balances (latest):")
        for b in st["balances"]:
            print(f"  {b['name']}: {b['balance']:,.2f} as of {b['as_of']} ({b['source']})")
    print("characters: " + (", ".join(f"{c['name']} ({c['since']} to {c['until']})" for c in st["characters"]) or "none"))
    print("connectors: " + (", ".join(f"{c['name']} {c['status']} {c['last_sync']}" for c in st["connectors"]) or "none"))


def cmd_balances(args):
    with ledger.connect() as con:
        if args.action == "set":
            ledger.set_balance(con, args.account, args.value, args.as_of or date.today())
            con.commit()
            print(f"set {args.account} = {args.value:,.2f} as of {args.as_of or date.today()}")
        else:
            for b in ledger.latest_balances(con):
                print(f"{b['name']} [{b['kind']}]: {b['balance']:,.2f} as of {b['as_of']} ({b['source']})")


def cmd_engine(args):
    """Manual inputs for Engine stats until connectors supply them."""
    cfg = ledger.load_config()
    inputs = cfg.setdefault("engine_inputs", {})
    if args.action == "set":
        inputs[args.key] = args.value
        ledger.save_config(cfg)
        print(f"engine input {args.key} = {args.value}")
    else:
        from .character import derive_engine_inputs
        raw = ["k401_employee_ytd", "roth_ira_ytd", "roth_eligible", "employer_stock_value", "investable_assets",
               "checking_balance", "m1_borrow_balance", "card_carry_balance"]
        derived = ["tax_shelter_pct_of_max", "idle_cash_months", "employer_stock_share_pct", "interest_bearing_debt"]
        print("raw inputs:")
        for k in raw:
            print(f"  {k}: {inputs.get(k, 'unset')}")
        d = derive_engine_inputs(inputs)
        print("derived (idle_cash_months also needs a profile; see `mint character build`):")
        for k in derived:
            v = d.get(k)
            print(f"  {k}: {'unset' if v is None else round(v, 2)}")


def cmd_reclassify(args):
    with ledger.connect() as con:
        n = ledger.reclassify_all(con)
        con.commit()
    print(f"reclassified {n} rows")


def cmd_reconcile(args):
    with ledger.connect() as con:
        n = ledger.reconcile_shortcut_rows(con, args.window)
        con.commit()
    print(f"superseded {n} wallet_shortcut rows matched by other sources")


def cmd_serve(args):
    from .serve import serve
    serve(args.host, args.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint", description="Local personal finance ledger and game engine.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create ~/.mint, the ledger, and the ingest token").set_defaults(fn=cmd_init)

    s = sub.add_parser("example", aliases=["demo"], help="write example transactions to CSV")
    s.add_argument("path")
    s.add_argument("--days", type=int, default=300)
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("import-csv", help="import a transactions CSV (Origin export or similar)")
    s.add_argument("path")
    s.add_argument("--source", default="origin", help="source label stored on each row (default: origin)")
    s.add_argument("--map", help="role=Column,... overrides (roles: date amount debit credit merchant category account type pending)")
    s.add_argument("--sign", choices=["auto", "neg-out", "pos-out"], default="auto")
    s.add_argument("--since", type=_d)
    s.add_argument("--until", type=_d)
    s.add_argument("--accounts", help="comma-separated substrings; import only matching account names")
    s.add_argument("--no-raw", action="store_true", help="do not keep the original row JSON in the ledger")
    s.set_defaults(fn=cmd_import_csv)

    s = sub.add_parser("profile", help="aggregate-only profile from the ledger")
    s.add_argument("--since", type=_d)
    s.add_argument("--until", type=_d)
    s.add_argument("--days", type=int, help="trailing window instead of since/until")
    s.add_argument("--accounts")
    s.add_argument("--out", help="directory for profile.md / profile.json")
    s.add_argument("--json", action="store_true")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_profile)

    s = sub.add_parser("character", help="build or show the rival's stat sheet")
    s.add_argument("action", choices=["build", "show"])
    s.add_argument("--name", default="Year One")
    s.add_argument("--since", type=_d)
    s.add_argument("--until", type=_d)
    s.add_argument("--days", type=int)
    s.add_argument("--accounts")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_character)

    s = sub.add_parser("week", help="score the trailing window against the rival")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--until", type=_d)
    s.add_argument("--vs", help="rival name (default: most recently built)")
    s.set_defaults(fn=cmd_week)

    s = sub.add_parser("status", help="what is in the ledger")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("balances", help="manual balance snapshots")
    s.add_argument("action", choices=["set", "list"])
    s.add_argument("--account")
    s.add_argument("--value", type=float)
    s.add_argument("--as-of", dest="as_of", type=_d)
    s.set_defaults(fn=cmd_balances)

    s = sub.add_parser("engine", help="manual inputs for Engine stats (until connectors supply them)")
    s.add_argument("action", choices=["set", "list"])
    s.add_argument("--key")
    s.add_argument("--value", type=float)
    s.set_defaults(fn=cmd_engine)

    sub.add_parser("reclassify", help="re-run bucket/kind rules over every row").set_defaults(fn=cmd_reclassify)

    s = sub.add_parser("reconcile", help="supersede Shortcut rows that a bank source has since confirmed")
    s.add_argument("--window", type=int, default=3)
    s.set_defaults(fn=cmd_reconcile)

    s = sub.add_parser("serve", help="HTTP receiver for the iPhone Shortcut")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    if args.cmd == "balances" and args.action == "set" and (not args.account or args.value is None):
        ap.error("balances set needs --account and --value")
    if args.cmd == "engine" and args.action == "set" and (not args.key or args.value is None):
        ap.error("engine set needs --key and --value")
    args.fn(args)


if __name__ == "__main__":
    main()
