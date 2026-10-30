"""Importers that write into the ledger. CSV (Origin and similar) for now."""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime

from . import ledger
from .normalize import detect_columns, outflow_amount, parse_amount, parse_date, resolve_sign


def read_csv_rows(path, cols, since=None, until=None, account_filters=None):
    rows, skipped = [], Counter()
    filters = [f.lower() for f in (account_filters or [])]
    with open(path, newline="", encoding="utf-8-sig") as f:
        for idx, raw in enumerate(csv.DictReader(f)):
            d, hour = parse_date(raw.get(cols.get("date", ""), ""))
            if d is None:
                skipped["bad_date"] += 1
                continue
            if since and d < since:
                skipped["before_window"] += 1
                continue
            if until and d > until:
                skipped["after_window"] += 1
                continue
            acct = (raw.get(cols.get("account", ""), "") or "").strip() or "Unknown account"
            if filters and not any(fl in acct.lower() for fl in filters):
                skipped["account_filtered"] += 1
                continue
            amt, dc_split = None, False
            if "amount" in cols:
                amt = parse_amount(raw.get(cols["amount"]))
            if amt is None and ("debit" in cols or "credit" in cols):
                deb = parse_amount(raw.get(cols.get("debit", ""), "")) or 0.0
                cre = parse_amount(raw.get(cols.get("credit", ""), "")) or 0.0
                amt, dc_split = cre - abs(deb), True
            if amt is None:
                skipped["bad_amount"] += 1
                continue
            pend_raw = (raw.get(cols.get("pending", ""), "") or "").strip().lower()
            rows.append({"idx": idx, "date": d, "hour": hour, "amount": amt, "dc_split": dc_split,
                         "type": (raw.get(cols.get("type", ""), "") or "").strip().lower(),
                         "merchant": (raw.get(cols.get("merchant", ""), "") or "").strip(),
                         "category": (raw.get(cols.get("category", ""), "") or "").strip(),
                         "account": acct, "pending": 1 if pend_raw in ("pending", "true", "yes", "1") else 0,
                         "raw": raw})
    return rows, skipped


def csv_to_memory_rows(path, overrides=None, sign="auto", since=None, until=None, account_filters=None):
    """For the standalone profiler: rows shaped for profile(), no ledger involved."""
    from .normalize import account_kind, bucket_for, classify, norm_merchant
    with open(path, newline="", encoding="utf-8-sig") as f:
        headers = next(csv.reader(f))
    cols = detect_columns(headers, overrides)
    if "date" not in cols or not ({"amount", "debit", "credit"} & set(cols)):
        raise ValueError(f"could not detect required columns. header={headers} detected={cols}. Use --map.")
    rows, skipped = read_csv_rows(path, cols, since, until, account_filters)
    if not rows:
        raise ValueError(f"no usable rows (skipped: {dict(skipped)})")
    convention, note = resolve_sign(rows, sign)
    kinds = {a: account_kind(a) for a in {r["account"] for r in rows}}
    peer = any(k == "peer_wallet" for k in kinds.values())
    out = []
    for r in rows:
        o = outflow_amount(r["amount"], r["type"], convention)
        b = bucket_for(r["category"], r["merchant"])
        out.append({"date": r["date"], "hour": r["hour"], "out": o, "merchant": r["merchant"], "category": r["category"],
                    "account": r["account"], "acct_kind": kinds[r["account"]], "bucket": b,
                    "kind": classify(o, kinds[r["account"]], r["category"], r["merchant"], b, peer, r["type"]),
                    "mkey": norm_merchant(r["merchant"]), "pending": r["pending"], "source": "csv"})
    return out, {"columns": cols, "skipped": dict(skipped), "sign_convention": convention, "sign_note": note}


def import_csv(con, path, source_name="csv", overrides=None, sign="auto", since=None, until=None,
               account_filters=None, keep_raw=True) -> dict:
    started = datetime.now()
    with open(path, newline="", encoding="utf-8-sig") as f:
        headers = next(csv.reader(f))
    cols = detect_columns(headers, overrides)
    if "date" not in cols or not ({"amount", "debit", "credit"} & set(cols)):
        raise ValueError(f"could not detect required columns. header={headers} detected={cols}. Use --map.")
    rows, skipped = read_csv_rows(path, cols, since, until, account_filters)
    if not rows:
        raise ValueError(f"no usable rows (skipped: {dict(skipped)})")
    convention, note = resolve_sign(rows, sign)

    # Register accounts first so peer-wallet detection sees the whole file.
    acct_ids = {}
    for a in sorted({r["account"] for r in rows}):
        acct_ids[a] = ledger.get_or_create_account(con, a, source_name)
    kinds = {r["name"]: r["kind"] for r in ledger.accounts(con)}
    peer = ledger.peer_wallet_present(con)

    # Content ids: identical tuples within one file get an occurrence index, so real duplicates
    # survive and re-importing the same export is idempotent.
    seen = Counter()
    added = 0
    for r in rows:
        o = outflow_amount(r["amount"], r["type"], convention)
        key = (r["account"], r["date"].isoformat(), round(o, 2), r["merchant"], r["category"])
        seen[key] += 1
        ext = ledger.content_id(*key, seen[key])
        if ledger.upsert_transaction(con, account_id=acct_ids[r["account"]], d=r["date"], hour=r["hour"], out=o,
                                     merchant=r["merchant"], category_src=r["category"], source=source_name,
                                     external_id=ext, raw=r["raw"] if keep_raw else None, pending=r["pending"],
                                     acct_kind=kinds[r["account"]], peer_present=peer, type_src=r["type"]):
            added += 1
    ledger.log_sync(con, source_name, started, added, note)
    con.commit()
    return {"rows_in_file": len(rows), "added": added, "duplicates": len(rows) - added, "skipped": dict(skipped),
            "columns": cols, "sign_convention": convention, "sign_note": note,
            "accounts": sorted(acct_ids)}
