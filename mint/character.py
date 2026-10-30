"""The rival: a stat sheet scored 0-100 on absolute scales, higher is better for wealth.

Why absolute scales: the rival is a fixed opponent built from a past window. If stats were
scaled to the user's own distribution, the rival would sit at 50 on everything by construction
and nothing could be beaten. So every stat has explicit anchors (best, worst), linear in
between, documented here so they can be argued with and re-tuned.

Two halves:
  Burn   - from transactions (needs only a profile dict)
  Engine - from the balance sheet (needs balances / contributions; scored when data exists)
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from .normalize import FIXED_BUCKETS, FOOD_OUT_BUCKETS


# IRS limits for 2026 (irs.gov, announced 2025-11-13).
LIMITS = {"k401_employee": 24500.0, "ira": 7500.0, "roth_phaseout_single": (153000.0, 168000.0)}


def derive_engine_inputs(inputs: dict, p: dict | None = None, today: date | None = None) -> dict:
    """Turn raw numbers set with `mint engine set` into the metrics the Engine stats score.

    Raw keys (all optional):
      k401_employee_ytd, roth_ira_ytd            dollars contributed this calendar year
      roth_eligible                              1 or 0; 0 drops the IRA limit from the target (income above phase-out)
      employer_stock_value, investable_assets    dollars
      checking_balance                           dollars (idle cash beyond one month of outflow is drag)
      m1_borrow_balance, card_carry_balance      dollars of interest-bearing debt
    Derived keys are only computed when not set directly.
    """
    out = dict(inputs or {})
    today = today or date.today()
    year_frac = today.timetuple().tm_yday / (366.0 if calendar.isleap(today.year) else 365.0)
    if out.get("tax_shelter_pct_of_max") is None:
        k, r = out.get("k401_employee_ytd"), out.get("roth_ira_ytd")
        if k is not None or r is not None:
            ira_part = LIMITS["ira"] if out.get("roth_eligible", 1) else 0.0
            target = (LIMITS["k401_employee"] + ira_part) * year_frac
            out["tax_shelter_pct_of_max"] = (100.0 * ((k or 0.0) + (r or 0.0)) / target) if target else None
            out["tax_shelter_target_ytd"] = round(target, 2)
    if out.get("employer_stock_share_pct") is None:
        ev, ia = out.get("employer_stock_value"), out.get("investable_assets")
        if ev is not None and ia:
            out["employer_stock_share_pct"] = 100.0 * ev / ia
    if out.get("idle_cash_months") is None:
        cash = out.get("checking_balance")
        monthly_out = (p or {}).get("flows", {}).get("monthly_out_ex_transfers") if p else None
        if cash is not None and monthly_out:
            out["idle_cash_months"] = max(0.0, cash / monthly_out - 1.0)
    if out.get("interest_bearing_debt") is None:
        parts = [out[k] for k in ("m1_borrow_balance", "card_carry_balance") if out.get(k) is not None]
        if parts:
            out["interest_bearing_debt"] = float(sum(parts))
    return out


def clamp_score(value, best, worst):
    """Linear 0-100 between worst and best. Works whether best < worst or best > worst."""
    if value is None:
        return None
    if best == worst:
        return 100.0 if value == best else 0.0
    t = (value - worst) / (best - worst)
    return round(max(0.0, min(1.0, t)) * 100.0, 1)


# Each stat: id, name, half, weight, description, anchors, and how to pull the metric from a profile.
# 'weekly' anchors are used when the scored window is shorter than 28 days.

def _bucket(p, b):
    return p.get("bucket_totals", {}).get(b, 0.0)


def burn_metrics(p: dict, days: int, reference_income_monthly: float | None = None,
                 bills_monthly_ex_fixed: float | None = None) -> dict:
    """Raw metrics for the Burn half from a profile dict over `days` days.

    Short windows (< 28 days) cannot see a whole pay cycle, so income ratios use
    `reference_income_monthly` (normally the rival's detected monthly income) and bills
    use `bills_monthly_ex_fixed` computed over a longer trailing window.
    """
    f, d, w, s = p["flows"], p["daily"], p["weekly"], p["sizes"]
    months = max(days / 30.44, 1e-9)
    disc = f["discretionary_total"]
    income = f["income"]
    food_out = sum(_bucket(p, b) for b in FOOD_OUT_BUCKETS)
    groceries = _bucket(p, "groceries")
    food_all = food_out + groceries
    delivery = _bucket(p, "delivery")
    rides = _bucket(p, "rideshare_transit")
    fees = f["fees"]
    peer_net = f["peer_out"] - f["peer_in"]
    rent = _bucket(p, "rent_housing")
    short = days < 28
    disc_monthly = disc / months
    if short:
        income_monthly = reference_income_monthly
        share = (100.0 * disc_monthly / income_monthly) if income_monthly else None
        bills = bills_monthly_ex_fixed
        rent_share = None
    else:
        income_monthly = (income / months) if income else None
        share = (100.0 * disc / income) if income else None
        bills = p.get("bills_monthly_ex_fixed", 0.0)
        rent_share = (100.0 * rent / income) if income else None
    return {
        "days": days,
        "discretionary_monthly": disc_monthly,
        "discretionary_share_of_income_pct": share,
        "income_monthly": income_monthly,
        "weekly_cv": w["cv"] if not short else None,
        "daily_cv": d["cv"],
        "top5_days_share_pct": d["top5pct_days_share_pct"],
        "top_day_share_pct": d.get("top_day_share_pct"),
        "spend_txns_per_day": d["avg_spend_txns_per_day"],
        "fri_sun_share_pct": d["fri_sun_share_pct"],
        "under_30_count_pct": s["under_30_count_pct"],
        "food_out_share_pct": (100.0 * food_out / food_all) if food_all else None,
        "delivery_share_of_food_out_pct": (100.0 * delivery / food_out) if food_out else None,
        "bills_monthly_ex_fixed": bills,
        "fees_monthly": fees / months,
        "rides_share_of_discretionary_pct": (100.0 * rides / disc) if disc else None,
        "peer_net_monthly": peer_net / months,
        "rent_share_of_income_pct": rent_share,
        "savings_rate_pct": f["savings_rate_pct"] if not short else None,
    }


BURN_STATS = [
    # id, name, weight, metric key(s) -> anchors. Scores of several sub-metrics are averaged when present.
    {"id": "burn_control", "name": "Burn Control", "weight": 3.0,
     "desc": "Discretionary spend as a share of income (or absolute $/month when no income rows).",
     "subs": [("discretionary_share_of_income_pct", 20.0, 70.0), ("discretionary_monthly", 1500.0, 6000.0)],
     "mode": "first_available"},
    {"id": "steadiness", "name": "Steadiness", "weight": 2.0,
     "desc": "Inverse spikiness of discretionary spend: week-to-week CV and share of spend landing in the top 5% of days.",
     "subs": [("weekly_cv", 0.25, 1.0), ("top5_days_share_pct", 15.0, 45.0)],
     "subs_short": [("daily_cv", 0.6, 1.6), ("top_day_share_pct", 25.0, 60.0)],
     "mode": "average"},
    {"id": "impulse_resistance", "name": "Impulse Resistance", "weight": 2.0,
     "desc": "Fewer small, frequent, weekend-loaded purchases.",
     "subs": [("spend_txns_per_day", 1.0, 4.0), ("fri_sun_share_pct", 45.0, 65.0), ("under_30_count_pct", 35.0, 70.0)],
     "mode": "average"},
    {"id": "kitchen_ratio", "name": "Kitchen Ratio", "weight": 2.0,
     "desc": "Groceries versus eating out, with delivery as a penalty inside eating out.",
     "subs": [("food_out_share_pct", 40.0, 90.0), ("delivery_share_of_food_out_pct", 10.0, 50.0)],
     "mode": "average"},
    {"id": "subscription_hygiene", "name": "Subscription Hygiene", "weight": 1.0,
     "desc": "Monthly bills excluding rent and utilities.",
     "subs": [("bills_monthly_ex_fixed", 50.0, 400.0)], "mode": "average"},
    {"id": "leak_seal", "name": "Leak Seal", "weight": 1.5,
     "desc": "Fees and interest paid per month. Zero is the only acceptable number.",
     "subs": [("fees_monthly", 0.0, 50.0)], "mode": "average"},
    {"id": "transit_discipline", "name": "Transit Discipline", "weight": 1.0,
     "desc": "Rideshare and transit as a share of discretionary spend.",
     "subs": [("rides_share_of_discretionary_pct", 3.0, 15.0)], "mode": "average"},
    {"id": "social_ledger", "name": "Social Ledger", "weight": 0.5,
     "desc": "Net peer payments out per month (Venmo, Apple Cash, Zelle).",
     "subs": [("peer_net_monthly", 100.0, 800.0)], "mode": "average"},
    {"id": "rent_load", "name": "Rent Load", "weight": 1.0, "structural": True,
     "desc": "Rent as a share of income. Structural: not part of the weekly contest.",
     "subs": [("rent_share_of_income_pct", 25.0, 45.0)], "mode": "average"},
]

ENGINE_STATS = [
    {"id": "savings_rate", "name": "Savings Rate", "weight": 3.0,
     "desc": "Income minus everything out except transfers, over income. Needs paychecks in the ledger.",
     "subs": [("savings_rate_pct", 50.0, 0.0)], "mode": "average"},
    {"id": "tax_shelter", "name": "Tax Shelter", "weight": 2.0, "needs": "401k contribution rate and Roth IRA contributions (set via `mint engine set`)",
     "subs": [("tax_shelter_pct_of_max", 100.0, 0.0)], "mode": "average",
     "desc": "Share of the annual 401k and Roth IRA limits being captured, with the employer match counted as the floor."},
    {"id": "cash_drag", "name": "Cash Drag", "weight": 1.5, "needs": "checking and savings balances (`mint balances set`)",
     "subs": [("idle_cash_months", 1.5, 6.0)], "mode": "average",
     "desc": "Months of spend sitting in checking beyond a one-month buffer. Idle cash is a wealth leak."},
    {"id": "concentration", "name": "Concentration", "weight": 1.5, "needs": "employer stock value and total investable assets",
     "subs": [("employer_stock_share_pct", 10.0, 50.0)], "mode": "average",
     "desc": "Employer stock as a share of investable assets."},
    {"id": "debt_cost", "name": "Debt Cost", "weight": 1.5, "needs": "M1 Borrow / card carry balances",
     "subs": [("interest_bearing_debt", 0.0, 10000.0)], "mode": "average",
     "desc": "Interest-bearing debt outstanding."},
]


def score_stat(stat: dict, metrics: dict, short: bool) -> dict:
    subs = stat.get("subs_short") if (short and stat.get("subs_short")) else stat["subs"]
    parts = []
    for key, best, worst in subs:
        v = metrics.get(key)
        sc = clamp_score(v, best, worst)
        parts.append({"metric": key, "value": None if v is None else round(v, 2), "best": best, "worst": worst, "score": sc})
        if stat.get("mode") == "first_available" and sc is not None:
            break
    scored = [x["score"] for x in parts if x["score"] is not None]
    score = round(sum(scored) / len(scored), 1) if scored else None
    return {"id": stat["id"], "name": stat["name"], "weight": stat["weight"], "desc": stat["desc"],
            "structural": bool(stat.get("structural")), "score": score, "parts": parts,
            "needs": stat.get("needs") if score is None else None}


def build_sheet(p: dict, days: int, engine_inputs: dict | None = None, name: str = "Rival",
                reference_income_monthly: float | None = None, bills_monthly_ex_fixed: float | None = None) -> dict:
    short = days < 28
    metrics = burn_metrics(p, days, reference_income_monthly, bills_monthly_ex_fixed)
    metrics.update(derive_engine_inputs(engine_inputs, p))
    burn = [score_stat(s, metrics, short) for s in BURN_STATS]
    engine = [score_stat(s, metrics, short) for s in ENGINE_STATS]

    def level(stats):
        scored = [(s["score"], s["weight"]) for s in stats if s["score"] is not None]
        if not scored:
            return None
        return round(sum(sc * w for sc, w in scored) / sum(w for _, w in scored), 1)

    contest = [s for s in burn if not s["structural"]]
    return {"name": name, "days": days, "short_window": short, "metrics": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in metrics.items()},
            "burn": burn, "engine": engine,
            "levels": {"burn": level(burn), "burn_contest": level(contest), "engine": level(engine),
                       "overall": level(burn + engine)}}


def render_sheet(sheet: dict) -> str:
    L = [f"# {sheet['name']}", f"Window: {sheet['days']} days" + (" (short window: daily-based steadiness)" if sheet["short_window"] else ""), ""]
    lv = sheet["levels"]
    L.append(f"Level: overall {lv['overall']}  |  burn {lv['burn']}  |  contest {lv['burn_contest']}  |  engine {lv['engine']}")
    L.append("")
    for half in ("burn", "engine"):
        L.append(f"## {half.capitalize()}")
        for s in sheet[half]:
            if s["score"] is None:
                L.append(f"- {s['name']}: unscored (needs {s['needs'] or 'data'})")
                continue
            detail = ", ".join(f"{x['metric']}={x['value']}" for x in s["parts"] if x["value"] is not None)
            tag = " [structural]" if s["structural"] else ""
            L.append(f"- {s['name']}: {s['score']:.0f}{tag}  ({detail})")
        L.append("")
    return "\n".join(L)


def compare(current: dict, rival: dict) -> dict:
    """Head-to-head on contest stats. Positive delta means current beats rival."""
    rmap = {s["id"]: s for s in rival["burn"]}
    rows, wins, losses = [], 0, 0
    for s in current["burn"]:
        if s["structural"]:
            continue
        r = rmap.get(s["id"])
        if not r or s["score"] is None or r["score"] is None:
            rows.append({"id": s["id"], "name": s["name"], "you": s["score"], "rival": r["score"] if r else None, "delta": None})
            continue
        delta = round(s["score"] - r["score"], 1)
        if abs(delta) < 0.5:
            delta = 0.0
        wins += delta > 0
        losses += delta < 0
        rows.append({"id": s["id"], "name": s["name"], "you": s["score"], "rival": r["score"], "delta": delta})
    return {"rows": rows, "wins": wins, "losses": losses,
            "you_level": current["levels"]["burn_contest"], "rival_level": rival["levels"]["burn_contest"]}


def render_scoreboard(cmp: dict, current: dict, rival_name: str, window_label: str) -> str:
    L = [f"{window_label} vs {rival_name}", f"Level {cmp['you_level']} vs {cmp['rival_level']}  |  {cmp['wins']} won, {cmp['losses']} lost", ""]
    for r in cmp["rows"]:
        if r["delta"] is None:
            you = "n/a" if r["you"] is None else f"{r['you']:.0f}"
            rv = "n/a" if r["rival"] is None else f"{r['rival']:.0f}"
            L.append(f"  {r['name']:<22} you {you:>5}  rival {rv:>5}   -")
        else:
            mark = "WIN " if r["delta"] > 0 else "LOSS" if r["delta"] < 0 else "TIE "
            L.append(f"  {r['name']:<22} you {r['you']:>5.0f}  rival {r['rival']:>5.0f}   {mark} {r['delta']:+.0f}")
    m = current["metrics"]
    L.append("")
    L.append(f"  discretionary {m['discretionary_monthly'] * current['days'] / 30.44:,.0f} over {current['days']} days"
             f"  |  {m['spend_txns_per_day']:.1f} buys/day  |  Fri-Sun {m['fri_sun_share_pct']:.0f}%  |  fees {m['fees_monthly'] * current['days'] / 30.44:,.0f}")
    return "\n".join(L)
