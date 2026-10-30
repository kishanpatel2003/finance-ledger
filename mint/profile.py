"""Aggregate-only profile of a set of classified transaction rows.

Input rows carry: date (date), hour, out (positive = money out), merchant, category, account,
acct_kind, bucket, kind, mkey. Output is a dict of aggregates; render_md turns it into Markdown.
No individual transactions appear in the output.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from .normalize import FIXED_BUCKETS

SPENDLIKE = ("spend", "fee", "cash", "peer_out")


def pct(x, total):
    return round(100.0 * x / total, 1) if total else 0.0


def r2(x):
    return round(float(x), 2)


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def gini(vals):
    vals = sorted(v for v in vals if v >= 0)
    n, s = len(vals), sum(vals)
    if n == 0 or s == 0:
        return 0.0
    cum = sum(i * v for i, v in enumerate(vals, 1))
    return round((2 * cum) / (n * s) - (n + 1) / n, 3)


def cv(vals):
    if len(vals) < 2:
        return 0.0
    m = statistics.mean(vals)
    return round(statistics.pstdev(vals) / m, 3) if m else 0.0


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def profile(rows, since: date | None = None, until: date | None = None) -> dict:
    if not rows:
        raise ValueError("no rows to profile")
    accounts = sorted({r["account"] for r in rows})
    acct_kinds = {}
    for r in rows:
        acct_kinds[r["account"]] = r.get("acct_kind") or "unknown"
    peer_wallet = any(k == "peer_wallet" for k in acct_kinds.values())

    start = since or min(r["date"] for r in rows)
    end = until or max(r["date"] for r in rows)
    n_days = (end - start).days + 1
    span_months = n_days / 30.44

    def is_spendlike(r):
        return r["kind"] in SPENDLIKE

    spend_rows = [r for r in rows if r["kind"] == "spend"]
    refunds = sum(-r["out"] for r in rows if r["kind"] == "refund")
    gross_spend = sum(r["out"] for r in spend_rows)
    fees = sum(r["out"] for r in rows if r["kind"] == "fee")
    cash = sum(r["out"] for r in rows if r["kind"] == "cash")
    peer_out = sum(r["out"] for r in rows if r["kind"] == "peer_out")
    peer_in = sum(-r["out"] for r in rows if r["kind"] == "peer_in")
    income = sum(-r["out"] for r in rows if r["kind"] == "income")
    other_in = sum(-r["out"] for r in rows if r["kind"] == "other_inflow")
    transfers_out = sum(r["out"] for r in rows if r["kind"] == "transfer" and r["out"] > 0)
    transfers_in = sum(-r["out"] for r in rows if r["kind"] == "transfer" and r["out"] < 0)
    net_spend = gross_spend - refunds
    total_out_ex_transfers = net_spend + fees + cash + peer_out - peer_in
    months = sorted({month_key(r["date"]) for r in rows})
    full_months = months[1:-1] if len(months) > 2 else months

    # daily series: all spend-like, and discretionary (fixed buckets removed)
    daily_all, daily = defaultdict(float), defaultdict(float)
    for r in rows:
        if is_spendlike(r):
            daily_all[r["date"]] += r["out"]
            if r["bucket"] not in FIXED_BUCKETS:
                daily[r["date"]] += r["out"]
    all_days = [start + timedelta(days=i) for i in range(n_days)]
    dvals = [max(0.0, daily.get(d, 0.0)) for d in all_days]
    dvals_all = [max(0.0, daily_all.get(d, 0.0)) for d in all_days]
    fixed_total = sum(r["out"] for r in rows if is_spendlike(r) and r["bucket"] in FIXED_BUCKETS)
    discretionary_total = sum(dvals)
    dsorted = sorted(dvals)
    dtotal = sum(dvals)
    top_n = max(1, math.ceil(0.05 * len(dvals)))
    top5_share = pct(sum(dsorted[-top_n:]), dtotal)
    top_day_share = pct(dsorted[-1], dtotal) if dsorted else 0.0
    nonzero = [v for v in dvals if v > 0]
    med_nonzero = statistics.median(nonzero) if nonzero else 0.0
    dmean = statistics.mean(dvals) if dvals else 0.0
    burst_days = sum(1 for v in dvals if dmean and v > 3 * dmean)

    weekly = defaultdict(float)
    for d, v in zip(all_days, dvals):
        weekly[week_start(d)] += v
    complete = [w for w in sorted(weekly) if w >= start and w + timedelta(days=6) <= end]
    wvals = [weekly[w] for w in complete]
    wsorted = sorted(wvals)

    by_dow = defaultdict(float)
    for d, v in zip(all_days, dvals):
        by_dow[d.weekday()] += v
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weeks_count = max(1e-9, n_days / 7.0)
    dow_avg = {dow_names[i]: r2(by_dow[i] / weeks_count) for i in range(7)}
    frisun = by_dow[4] + by_dow[5] + by_dow[6]

    tod = None
    if any(r.get("hour") is not None for r in spend_rows):
        tod = defaultdict(float)
        for r in spend_rows:
            h = r.get("hour")
            if h is None:
                continue
            slot = ("late_night" if h >= 22 or h < 5 else "morning" if h < 11 else "midday" if h < 14
                    else "afternoon" if h < 18 else "evening")
            tod[slot] += r["out"]
        tod = {k: {"amount": r2(v), "share_pct": pct(v, gross_spend)} for k, v in sorted(tod.items())}

    sizes = sorted(r["out"] for r in spend_rows)
    small15 = [s for s in sizes if s < 15]
    small30 = [s for s in sizes if s < 30]
    big100 = [s for s in sizes if s >= 100]

    bucket_tot, bucket_cnt = defaultdict(float), Counter()
    bucket_month = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r["kind"] in SPENDLIKE:
            b = r["bucket"] if r["kind"] == "spend" else {"fee": "fees_interest", "cash": "cash", "peer_out": "peer"}[r["kind"]]
            bucket_tot[b] += r["out"]
            bucket_cnt[b] += 1
            bucket_month[b][month_key(r["date"])] += r["out"]
    spendlike_total = sum(bucket_tot.values())
    bucket_table = []
    for b, tot in sorted(bucket_tot.items(), key=lambda kv: -kv[1]):
        mvals = [bucket_month[b].get(m, 0.0) for m in full_months]
        bucket_table.append({"bucket": b, "total": r2(tot), "share_pct": pct(tot, spendlike_total),
                             "monthly_avg": r2(tot / span_months), "monthly_cv": cv(mvals), "txns": bucket_cnt[b],
                             "avg_txn": r2(tot / bucket_cnt[b]) if bucket_cnt[b] else 0.0})
    bucket_totals = {b: r2(t) for b, t in bucket_tot.items()}

    cat_tot = defaultdict(float)
    for r in spend_rows:
        cat_tot[r["category"] or "(blank)"] += r["out"]
    cat_table = [{"category": c, "total": r2(t), "share_pct": pct(t, gross_spend)}
                 for c, t in sorted(cat_tot.items(), key=lambda kv: -kv[1])[:15]]
    uncategorized_share = pct(cat_tot.get("(blank)", 0.0) + cat_tot.get("Uncategorized", 0.0), gross_spend)

    acct_table = []
    for a in accounts:
        rs = [r for r in rows if r["account"] == a]
        sp = sum(r["out"] for r in rs if is_spendlike(r))
        acct_table.append({"account": a, "kind": acct_kinds[a], "spend_like": r2(sp), "share_pct": pct(sp, spendlike_total),
                           "txns": len(rs), "spend_txns": sum(1 for r in rs if is_spendlike(r)),
                           "first": min(r["date"] for r in rs).isoformat(), "last": max(r["date"] for r in rs).isoformat()})
    acct_table.sort(key=lambda x: -x["spend_like"])

    monthly = []
    for m in months:
        rs = [r for r in rows if month_key(r["date"]) == m]
        sp = sum(r["out"] for r in rs if r["kind"] == "spend") - sum(-r["out"] for r in rs if r["kind"] == "refund")
        inc = sum(-r["out"] for r in rs if r["kind"] == "income")
        po = sum(r["out"] for r in rs if r["kind"] == "peer_out")
        pi = sum(-r["out"] for r in rs if r["kind"] == "peer_in")
        fe = sum(r["out"] for r in rs if r["kind"] == "fee")
        ca = sum(r["out"] for r in rs if r["kind"] == "cash")
        tout = sum(r["out"] for r in rs if r["kind"] == "transfer" and r["out"] > 0)
        monthly.append({"month": m, "net_spend": r2(sp), "peer_net": r2(po - pi), "fees": r2(fe), "cash": r2(ca),
                        "income": r2(inc), "transfers_out": r2(tout), "net": r2(inc - sp - fe - ca - (po - pi)),
                        "txns": len(rs), "active_days": len({r["date"] for r in rs})})
    mspend = [x["net_spend"] for x in (monthly[1:-1] if len(monthly) > 2 else monthly)]

    m_tot, m_cnt, m_bucket = defaultdict(float), Counter(), {}
    for r in spend_rows:
        m_tot[r["mkey"]] += r["out"]
        m_cnt[r["mkey"]] += 1
        m_bucket[r["mkey"]] = r["bucket"]
    top_amt = [{"merchant": k, "bucket": m_bucket[k], "total": r2(v), "txns": m_cnt[k], "avg": r2(v / m_cnt[k])}
               for k, v in sorted(m_tot.items(), key=lambda kv: -kv[1])[:15]]
    top_cnt = [{"merchant": k, "bucket": m_bucket[k], "txns": c, "total": r2(m_tot[k]), "avg": r2(m_tot[k] / c)}
               for k, c in m_cnt.most_common(15)]
    top10_share = pct(sum(v for _, v in sorted(m_tot.items(), key=lambda kv: -kv[1])[:10]), gross_spend)

    groups = defaultdict(list)
    for r in spend_rows:
        groups[r["mkey"]].append(r)
    bills, habits = [], []
    for k, rs in groups.items():
        if len(rs) < 3:
            continue
        ds = sorted(r["date"] for r in rs)
        gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
        if not gaps:
            continue
        mg = statistics.median(gaps)
        amts = [r["out"] for r in rs]
        amt_cv, spread, med_amt = cv(amts), max(amts) - min(amts), statistics.median(amts)
        cadence = ("weekly" if 6 <= mg <= 8 else "biweekly" if 12 <= mg <= 16 else "monthly" if 25 <= mg <= 36
                   else "quarterly" if 80 <= mg <= 100 else "annual" if 340 <= mg <= 390 else None)
        if cadence in ("monthly", "quarterly", "annual") and (amt_cv <= 0.05 or spread <= 1.0):
            bills.append({"merchant": k, "bucket": m_bucket[k], "cadence": cadence, "typical_amount": r2(med_amt),
                          "monthly_equiv": r2(med_amt * 30.44 / mg), "occurrences": len(rs),
                          "first": ds[0].isoformat(), "last": ds[-1].isoformat()})
        elif len(rs) >= 8 and mg <= 16:
            weeks = max(1.0, ((ds[-1] - ds[0]).days + 1) / 7.0)
            habits.append({"merchant": k, "bucket": m_bucket[k], "per_week": r2(len(rs) / weeks),
                           "avg_amount": r2(statistics.mean(amts)), "monthly_spend": r2(sum(amts) / span_months),
                           "occurrences": len(rs)})
    bills.sort(key=lambda x: -x["monthly_equiv"])
    habits.sort(key=lambda x: -x["monthly_spend"])
    bills_ex_fixed = sum(x["monthly_equiv"] for x in bills if x["bucket"] not in FIXED_BUCKETS)

    inc_src, inc_cnt = defaultdict(float), Counter()
    for r in rows:
        if r["kind"] == "income":
            inc_src[r["mkey"]] += -r["out"]
            inc_cnt[r["mkey"]] += 1
    income_sources = [{"source": k, "total": r2(v), "count": inc_cnt[k]} for k, v in sorted(inc_src.items(), key=lambda kv: -kv[1])[:8]]
    monthly_income = income / span_months if income else 0.0
    monthly_out = total_out_ex_transfers / span_months
    savings_rate = round(100.0 * (income - total_out_ex_transfers) / income, 1) if income else None

    return {
        "coverage": {"start": start.isoformat(), "end": end.isoformat(), "days": n_days, "months_touched": months,
                     "span_months": round(span_months, 2), "rows": len(rows), "accounts": accounts,
                     "account_kinds": acct_kinds, "row_kinds": dict(Counter(r["kind"] for r in rows)),
                     "uncategorized_share_pct": uncategorized_share, "peer_wallet_present": peer_wallet},
        "flows": {"gross_spend": r2(gross_spend), "refunds": r2(refunds), "net_spend": r2(net_spend), "fees": r2(fees),
                  "cash": r2(cash), "peer_out": r2(peer_out), "peer_in": r2(peer_in), "income": r2(income),
                  "other_inflows": r2(other_in), "transfers_out": r2(transfers_out), "transfers_in": r2(transfers_in),
                  "total_out_ex_transfers": r2(total_out_ex_transfers), "monthly_out_ex_transfers": r2(monthly_out),
                  "monthly_income": r2(monthly_income), "savings_rate_pct": savings_rate, "income_sources": income_sources,
                  "fixed_total": r2(fixed_total), "fixed_monthly": r2(fixed_total / span_months),
                  "discretionary_total": r2(discretionary_total), "discretionary_monthly": r2(discretionary_total / span_months),
                  "discretionary_share_of_income_pct": round(100.0 * discretionary_total / income, 1) if income else None,
                  "fixed_share_of_income_pct": round(100.0 * fixed_total / income, 1) if income else None},
        "daily": {"basis": "discretionary spend-like outflows (rent, utilities, insurance excluded); refunds not netted at day level",
                  "all_spend_mean": r2(statistics.mean(dvals_all)) if dvals_all else 0,
                  "all_spend_max": r2(max(dvals_all)) if dvals_all else 0,
                  "all_spend_top5pct_days_share_pct": pct(sum(sorted(dvals_all)[-top_n:]), sum(dvals_all)),
                  "mean": r2(dmean), "median_all_days": r2(statistics.median(dvals)) if dvals else 0,
                  "median_nonzero_day": r2(med_nonzero), "p90": r2(percentile(dsorted, 0.90)),
                  "p99": r2(percentile(dsorted, 0.99)), "max": r2(dsorted[-1]) if dsorted else 0,
                  "cv": cv(dvals), "gini": gini(dvals), "top5pct_days_share_pct": top5_share, "top_day_share_pct": top_day_share,
                  "zero_spend_days_pct": pct(sum(1 for v in dvals if v == 0), len(dvals)),
                  "burst_days_over_3x_mean": burst_days,
                  "max_over_median_nonzero": r2(dsorted[-1] / med_nonzero) if med_nonzero else 0,
                  "avg_spend_txns_per_day": r2(len(spend_rows) / n_days),
                  "dow_avg": dow_avg, "fri_sun_share_pct": pct(frisun, dtotal), "time_of_day": tod},
        "weekly": {"complete_weeks": len(wvals), "mean": r2(statistics.mean(wvals)) if wvals else 0,
                   "median": r2(statistics.median(wvals)) if wvals else 0,
                   "sd": r2(statistics.pstdev(wvals)) if len(wvals) > 1 else 0, "cv": cv(wvals),
                   "p25": r2(percentile(wsorted, 0.25)), "p75": r2(percentile(wsorted, 0.75)),
                   "p90": r2(percentile(wsorted, 0.90)), "max": r2(wsorted[-1]) if wsorted else 0,
                   "min": r2(wsorted[0]) if wsorted else 0},
        "monthly": monthly,
        "monthly_spend_cv_full_months": cv(mspend),
        "sizes": {"spend_txns": len(sizes), "median_txn": r2(statistics.median(sizes)) if sizes else 0,
                  "mean_txn": r2(statistics.mean(sizes)) if sizes else 0,
                  "under_15_count_pct": pct(len(small15), len(sizes)), "under_15_amount_pct": pct(sum(small15), gross_spend),
                  "under_30_count_pct": pct(len(small30), len(sizes)), "under_30_amount_pct": pct(sum(small30), gross_spend),
                  "over_100_count_pct": pct(len(big100), len(sizes)), "over_100_amount_pct": pct(sum(big100), gross_spend)},
        "buckets": bucket_table,
        "bucket_totals": bucket_totals,
        "export_categories_top": cat_table,
        "accounts": acct_table,
        "merchants_top_by_amount": top_amt,
        "merchants_top_by_count": top_cnt,
        "top10_merchant_share_pct": top10_share,
        "bills": bills, "bills_monthly_total": r2(sum(x["monthly_equiv"] for x in bills)),
        "bills_monthly_ex_fixed": r2(bills_ex_fixed),
        "habits": habits, "habits_monthly_total": r2(sum(x["monthly_spend"] for x in habits)),
    }


# ----------------------------------------------------------------------------
# Markdown rendering
# ----------------------------------------------------------------------------

def md_table(rows, cols, headers=None):
    if not rows:
        return "_none_\n"
    headers = headers or cols
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out) + "\n"


def render_md(p, meta):
    c, f, d, w, s = p["coverage"], p["flows"], p["daily"], p["weekly"], p["sizes"]
    L = ["# Mint sample profile\n",
         f"Generated {meta.get('generated', '')} from `{meta.get('source', '')}` ({c['rows']} rows). {meta.get('sign_note', '')}\n",
         f"Window {c['start']} to {c['end']} ({c['days']} days, {c['span_months']} months). Accounts: {', '.join(c['accounts'])}. "
         f"Uncategorized share of spend: {c['uncategorized_share_pct']}%.\n"]
    if c["peer_wallet_present"]:
        L.append("Peer wallet present: bank-side Venmo/Apple Cash funding rows were treated as transfers to avoid double counting.\n")
    L.append("Row kinds: " + ", ".join(f"{k} {v}" for k, v in sorted(c["row_kinds"].items())) + "\n")
    L.append("## Flows\n")
    L.append(md_table([
        {"k": "Net spend (gross minus refunds)", "v": f"{f['net_spend']:,}"},
        {"k": "Fees and interest", "v": f"{f['fees']:,}"},
        {"k": "Cash withdrawals", "v": f"{f['cash']:,}"},
        {"k": "Peer out / in", "v": f"{f['peer_out']:,} / {f['peer_in']:,}"},
        {"k": "Total out excluding transfers", "v": f"{f['total_out_ex_transfers']:,}"},
        {"k": "Monthly out excluding transfers", "v": f"{f['monthly_out_ex_transfers']:,}"},
        {"k": "Income (detected)", "v": f"{f['income']:,}"},
        {"k": "Monthly income (detected)", "v": f"{f['monthly_income']:,}"},
        {"k": "Other inflows (unclassified)", "v": f"{f['other_inflows']:,}"},
        {"k": "Transfers out / in (excluded)", "v": f"{f['transfers_out']:,} / {f['transfers_in']:,}"},
        {"k": "Savings rate proxy", "v": f"{f['savings_rate_pct']}%" if f["savings_rate_pct"] is not None else "n/a (no income rows)"},
        {"k": "Fixed (rent, utilities, insurance) monthly", "v": f"{f['fixed_monthly']:,}" + (f" ({f['fixed_share_of_income_pct']}% of income)" if f["fixed_share_of_income_pct"] is not None else "")},
        {"k": "Discretionary monthly (everything else spend-like)", "v": f"{f['discretionary_monthly']:,}" + (f" ({f['discretionary_share_of_income_pct']}% of income)" if f["discretionary_share_of_income_pct"] is not None else "")},
    ], ["k", "v"], ["Measure", "USD"]))
    if f["income_sources"]:
        L.append("Income sources: " + "; ".join(f"{x['source']} ({x['count']}x, {x['total']:,})" for x in f["income_sources"]) + "\n")
    L.append("## Spend by bucket\n")
    L.append(md_table(p["buckets"], ["bucket", "total", "share_pct", "monthly_avg", "monthly_cv", "txns", "avg_txn"],
                      ["Bucket", "Total", "Share %", "Monthly avg", "Month CV", "Txns", "Avg txn"]))
    L.append("Export's own top categories (as labeled by the source):\n")
    L.append(md_table(p["export_categories_top"], ["category", "total", "share_pct"], ["Category", "Total", "Share %"]))
    L.append("## Spikiness\n")
    L.append(f"Basis: {d['basis']}. Including fixed costs, the daily mean is {d['all_spend_mean']}, the max day {d['all_spend_max']}, "
             f"and the top 5% of days carry {d['all_spend_top5pct_days_share_pct']}%.\n")
    L.append(md_table([
        {"k": "Daily mean / median (all days) / median nonzero day", "v": f"{d['mean']} / {d['median_all_days']} / {d['median_nonzero_day']}"},
        {"k": "Daily p90 / p99 / max", "v": f"{d['p90']} / {d['p99']} / {d['max']}"},
        {"k": "Daily CV / Gini", "v": f"{d['cv']} / {d['gini']}"},
        {"k": "Share of spend in top 5% of days", "v": f"{d['top5pct_days_share_pct']}%"},
        {"k": "Zero-spend days", "v": f"{d['zero_spend_days_pct']}%"},
        {"k": "Burst days (over 3x daily mean)", "v": d["burst_days_over_3x_mean"]},
        {"k": "Max day over median nonzero day", "v": f"{d['max_over_median_nonzero']}x"},
        {"k": "Fri-Sun share of spend", "v": f"{d['fri_sun_share_pct']}%"},
        {"k": "Weekly mean / median / CV (complete weeks)", "v": f"{w['mean']} / {w['median']} / {w['cv']} ({w['complete_weeks']} weeks)"},
        {"k": "Weekly p25 / p75 / p90 / max", "v": f"{w['p25']} / {w['p75']} / {w['p90']} / {w['max']}"},
        {"k": "Month-to-month CV (full months)", "v": p["monthly_spend_cv_full_months"]},
    ], ["k", "v"], ["Measure", "Value"]))
    L.append("Average spend by weekday: " + ", ".join(f"{k} {v}" for k, v in d["dow_avg"].items()) + "\n")
    L.append(("Time of day: " + ", ".join(f"{k} {v['share_pct']}%" for k, v in d["time_of_day"].items()) + "\n")
             if d["time_of_day"] else "Time of day: not available (dates only).\n")
    L.append("## Transaction sizes\n")
    L.append(md_table([
        {"k": "Spend transactions / per day", "v": f"{s['spend_txns']} / {d['avg_spend_txns_per_day']}"},
        {"k": "Median / mean transaction", "v": f"{s['median_txn']} / {s['mean_txn']}"},
        {"k": "Under $15: share of count / of amount", "v": f"{s['under_15_count_pct']}% / {s['under_15_amount_pct']}%"},
        {"k": "Under $30: share of count / of amount", "v": f"{s['under_30_count_pct']}% / {s['under_30_amount_pct']}%"},
        {"k": "$100 and over: share of count / of amount", "v": f"{s['over_100_count_pct']}% / {s['over_100_amount_pct']}%"},
    ], ["k", "v"], ["Measure", "Value"]))
    L.append("## Monthly\n")
    L.append(md_table(p["monthly"], ["month", "net_spend", "peer_net", "fees", "cash", "income", "transfers_out", "net", "txns", "active_days"],
                      ["Month", "Net spend", "Peer net", "Fees", "Cash", "Income", "Transfers out", "Net", "Txns", "Active days"]))
    L.append("First and last months are usually partial.\n")
    L.append("## Accounts\n")
    L.append(md_table(p["accounts"], ["account", "kind", "spend_like", "share_pct", "spend_txns", "txns", "first", "last"],
                      ["Account", "Kind", "Spend-like out", "Share %", "Spend txns", "All txns", "First", "Last"]))
    L.append("## Merchants\n")
    L.append(f"Top 10 merchants carry {p['top10_merchant_share_pct']}% of spend.\n")
    L.append("By amount:\n")
    L.append(md_table(p["merchants_top_by_amount"], ["merchant", "bucket", "total", "txns", "avg"], ["Merchant", "Bucket", "Total", "Txns", "Avg"]))
    L.append("By count:\n")
    L.append(md_table(p["merchants_top_by_count"], ["merchant", "bucket", "txns", "total", "avg"], ["Merchant", "Bucket", "Txns", "Total", "Avg"]))
    L.append("## Bills and subscriptions (fixed amount, monthly or slower)\n")
    L.append(f"Monthly-equivalent total: {p['bills_monthly_total']:,} (excluding rent and utilities: {p['bills_monthly_ex_fixed']:,})\n")
    L.append(md_table(p["bills"], ["merchant", "bucket", "cadence", "typical_amount", "monthly_equiv", "occurrences", "first", "last"],
                      ["Merchant", "Bucket", "Cadence", "Typical", "Monthly equiv", "Times", "First", "Last"]))
    L.append("## Habits (same merchant, 8+ visits, at least every ~2 weeks)\n")
    L.append(f"Monthly spend across habits: {p['habits_monthly_total']:,}\n")
    L.append(md_table(p["habits"], ["merchant", "bucket", "per_week", "avg_amount", "monthly_spend", "occurrences"],
                      ["Merchant", "Bucket", "Per week", "Avg", "Monthly", "Times"]))
    L.append("\n_Aggregates only. No individual transactions appear in this report._\n")
    return "\n".join(L)
