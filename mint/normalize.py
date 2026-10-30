"""Parsing and classification shared by every importer and analysis.

Amount convention everywhere inside Mint: positive = money OUT of the account,
negative = money IN. This matches Plaid's convention.
"""
from __future__ import annotations

import re
import statistics
import sys
from datetime import date, datetime

# ----------------------------------------------------------------------------
# Column detection for CSV-like sources
# ----------------------------------------------------------------------------

ROLE_CANDIDATES = {
    "date": ["transaction date", "date", "posted date", "post date", "trans date", "authorized date"],
    "amount": ["amount", "transaction amount", "amt", "value"],
    "debit": ["debit", "withdrawal", "withdrawals", "outflow", "money out"],
    "credit": ["credit", "deposit", "deposits", "inflow", "money in"],
    "merchant": ["merchant", "merchant name", "name", "description", "payee", "original description", "details", "memo"],
    "category": ["category", "category name", "parent category", "top category"],
    "account": ["account", "account name", "account_name", "card", "source"],
    "type": ["type", "transaction type", "debit/credit", "direction"],
    "pending": ["pending", "status"],
}

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y",
    "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%b %d %Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
]


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9/]+", " ", (h or "").strip().lower()).strip()


def detect_columns(headers, overrides=None):
    overrides = overrides or {}
    normed = {norm_header(h): h for h in headers}
    cols = {}
    for role, cands in ROLE_CANDIDATES.items():
        if role in overrides:
            want = norm_header(overrides[role])
            if want in normed:
                cols[role] = normed[want]
            elif overrides[role] in headers:
                cols[role] = overrides[role]
            else:
                raise ValueError(f"--map: column '{overrides[role]}' for role '{role}' not found in header: {headers}")
            continue
        for c in cands:
            if c in normed:
                cols[role] = normed[c]
                break
    return cols


def parse_amount(s):
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    t = t.replace("$", "").replace(",", "").replace(" ", "").replace("USD", "")
    if t.endswith("-"):
        neg, t = True, t[:-1]
    if t.startswith("+"):
        t = t[1:]
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def parse_date(s):
    """Return (date, hour or None)."""
    t = (s or "").strip()
    if not t:
        return None, None
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(t, fmt)
            return dt.date(), (dt.hour if "%H" in fmt else None)
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})", t)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date(), int(m.group(2))
    m = re.match(r"(\d{4}-\d{2}-\d{2})", t)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date(), None
    return None, None


# ----------------------------------------------------------------------------
# Buckets: what kind of spend. Ordered; first match on "category | merchant" wins.
# ----------------------------------------------------------------------------

BUCKET_RULES = [
    ("rent_housing", ["rent", "mortgage", "landlord", "housing", "apartment", "bilt", "lease"]),
    ("utilities", ["utilit", "con ed", "coned", "consolidated edison", "national grid", "electric", "verizon", "at&t", "t-mobile", "tmobile", "spectrum", "optimum", "phone bill", "wireless", "mint mobile", "visible"]),
    ("insurance_taxes", ["insurance", "irs", "nys dtf", "tax payment", "dmv"]),
    ("peer", ["venmo", "zelle", "apple cash", "cash app", "cashapp", "paypal"]),
    ("fees_interest", ["fee", "interest charge", "interest charged", "finance charge", "late charge", "penalty", "surcharge", "foreign transaction"]),
    ("cash", ["atm", "cash withdrawal"]),
    ("delivery", ["doordash", "uber eats", "ubereats", "grubhub", "seamless", "caviar", "postmates", "gopuff", "instacart", "fresh direct", "freshdirect", "getir"]),
    ("convenience", ["convenience", "7-eleven", "7 eleven", "seven eleven", "bodega", "corner store", "circle k", "wawa"]),
    ("groceries", ["grocer", "trader joe", "whole foods", "wegmans", "key food", "fairway", "supermarket", "c-town", "ctown", "deli", "h mart", "hmart", "westside market", "morton williams", "gristedes", "food emporium", "target grocery"]),
    ("coffee", ["coffee", "cafe", "café", "starbucks", "blue bottle", "dunkin", "espresso", "matcha", "roaster", "roastery", "bakery", "juice"]),
    ("subscriptions", ["subscription", "netflix", "spotify", "hulu", "hbo", "disney", "apple.com/bill", "apple services", "icloud", "youtube", "prime video", "openai", "chatgpt", "anthropic", "claude.ai", "github", "notion", "adobe", "google one", "google storage", "dropbox", "nytimes", "nyt", "substack", "patreon", "audible", "kindle", "peloton", "strava", "amazon prime", "membership"]),
    ("personal_care", ["personal care", "barber", "haircut", "salon", "spa", "nails", "laundry", "laundromat", "dry clean", "wash & fold", "wash and fold", "grooming"]),
    ("fitness_health", ["gym", "fitness", "equinox", "crunch", "blink", "planet fitness", "classpass", "barry", "soulcycle", "yoga", "pilates", "pharmacy", "cvs", "walgreens", "duane reade", "doctor", "dental", "medical", "health", "one medical", "therapy", "vision", "rite aid", "urgent care"]),
    ("bars_nightlife", ["bar", "pub", "nightlife", "club", "lounge", "liquor", "wine", "brewery", "alcohol", "cocktail", "tavern", "beer", "taproom", "speakeasy"]),
    ("dining", ["restaurant", "dining", "drinks & dining", "food & drink", "food and drink", "food & dining", "fast food", "pizza", "sushi", "ramen", "taco", "burger", "chipotle", "sweetgreen", "cava", "kitchen", "grill", "diner", "bistro", "thai", "indian", "chinese", "mexican", "halal", "noodle", "dumpling", "shake shack", "mcdonald", "chick-fil-a", "popeyes", "wendy", "just salad", "dig inn", "eatery", "trattoria", "osteria", "cantina", "steakhouse", "bbq", "korean", "japanese", "italian", "vietnamese", "pho", "banh mi", "bagel", "food"]),
    ("rideshare_transit", ["auto & transport", "transport", "uber", "lyft", "taxi", "cab", "mta", "metrocard", "omny", "citi bike", "citibike", "transit", "subway", "nj transit", "lirr", "metro-north", "amtrak", "revel", "parking", "toll", "path"]),
    ("household", ["household", "home depot", "lowe's", "bed bath", "cleaning", "furniture", "hardware"]),
    ("shopping", ["amazon", "amzn", "shopping", "clothing", "apparel", "nike", "uniqlo", "zara", "target", "walmart", "best buy", "apple store", "electronics", "merchandise", "retail", "ikea", "home goods", "homegoods", "sephora", "nordstrom", "ssense", "etsy", "ebay", "costco", "cb2", "west elm", "container store", "muji", "lululemon", "abercrombie", "j.crew", "jcrew", "aritzia"]),
    ("entertainment", ["entertainment", "movie", "cinema", "amc", "theater", "theatre", "concert", "ticketmaster", "stubhub", "dice", "resident advisor", "museum", "steam", "playstation", "xbox", "nintendo", "bowling", "arcade", "comedy", "eventbrite", "fever", "axs"]),
    ("travel", ["travel", "airline", "airlines", "delta", "united", "jetblue", "american air", "southwest", "spirit", "frontier", "hotel", "airbnb", "vrbo", "marriott", "hilton", "hyatt", "expedia", "booking.com", "kayak", "hopper", "rental car", "hertz", "avis", "enterprise", "flight", "tsa", "lounge"]),
    ("education", ["course", "udemy", "coursera", "tuition", "bookstore", "strand", "barnes", "textbook", "class"]),
    ("gifts_donations", ["gift", "donation", "charity", "gofundme", "flowers"]),
]
SHORT = 4  # keywords this short or shorter must match on word boundaries
FIXED_BUCKETS = {"rent_housing", "utilities", "insurance_taxes"}
FOOD_OUT_BUCKETS = {"dining", "delivery", "coffee", "bars_nightlife", "convenience"}


def _compile_rules():
    out = []
    for bucket, kws in BUCKET_RULES:
        pats = []
        for kw in kws:
            esc = re.escape(kw)
            pats.append(r"\b" + esc + r"\b" if len(kw) <= SHORT else esc)
        out.append((bucket, re.compile("|".join(pats))))
    return out


COMPILED_RULES = _compile_rules()

TRANSFER_WORDS = [
    "transfer", "xfer", "autopay", "auto pay", "auto-pay", "automatic payment", "online payment",
    "payment thank you", "payment - thank you", "thank you", "epayment", "e-payment", "internet payment",
    "mobile payment", "card payment", "cc payment", "credit crd", "credit card", "ach pmt", "web pmt",
    "to savings", "from savings", "to checking", "from checking", "brokerage", "investment", "contribution",
    "robinhood", "m1 finance", "fidelity", "etrade", "e*trade", "vanguard", "schwab", "wealthfront",
    "betterment", "coinbase", "apple savings", "marcus", "ally bank", "sofi", "acorns", "public.com",
]
ISSUER_WORDS = ["amex", "american express", "chase", "apple card", "applecard", "gsbank", "goldman", "capital one",
                "citi", "discover", "barclay", "wells", "synchrony", "bank of america", "bofa"]
INCOME_WORDS = ["payroll", "direct dep", "direct deposit", "dir dep", "salary", "paycheck", "wages", "adp", "gusto",
                "workday", "rippling", "justworks", "trinet", "interest paid", "interest payment", "interest earned",
                "dividend", "tax refund", "irs treas", "nys dtf refund", "bonus", "reimbursement", "income", "cash back",
                "cashback", "daily cash", "rewards", "statement credit"]
CARD_WORDS = ["card", "visa", "amex", "american express", "mastercard", "sapphire", "freedom", "gold", "platinum",
              "credit", "cash rewards", "active cash", "discover"]
PEER_ACCOUNT_WORDS = ["venmo", "apple cash", "cash app", "cashapp", "paypal", "zelle"]
# Wallets that hold a balance you top up. Zelle is excluded on purpose: it moves bank to bank,
# so a Zelle payment is a real outflow, never the funding leg of a wallet in the ledger.
FUNDABLE_WALLET_WORDS = ["venmo", "apple cash", "cash app", "cashapp", "paypal"]
REFUND_WORDS = ["refund", "return", "reversal", "credit adjustment", "chargeback", "dispute"]


def bucket_for(category: str, merchant: str) -> str:
    text = f"{_flat(category)} | {_flat(merchant)}"
    for bucket, pat in COMPILED_RULES:
        if pat.search(text):
            return bucket
    return "other"


def _flat(s: str) -> str:
    """Lowercase and flatten exotic whitespace (Origin writes non-breaking spaces in Apple account names)."""
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ").replace("\u202f", " ")).strip().lower()


def account_kind(name: str) -> str:
    n = _flat(name)
    if any(w in n for w in PEER_ACCOUNT_WORDS):
        return "peer_wallet"
    if any(w in n for w in ["saving", "hysa", "money market"]):
        return "savings"
    if any(w in n for w in ["checking", "clear access", "everyday", "spending account"]):
        return "checking"
    if any(w in n for w in ["brokerage", "roth", "ira", "401", "invest", "robinhood", "m1", "etrade", "e*trade", "fidelity", "janney", "osaic", "pershing"]):
        return "investment"
    if any(w in n for w in CARD_WORDS):
        return "card"
    return "unknown"


# Values an export's own type column may carry that we trust over keyword guessing.
EXPLICIT_TYPES = {"expense", "income", "transfer"}

# Destinations that make a row a movement of your own money, whatever the export labels it.
# Origin types recurring M1 investing as "Expense"; counting it as spending would be wrong.
STRONG_TRANSFER_RE = re.compile(
    r"\b(transfer|xfer|transf)\b|"
    r"(m1 payments|m1 finance|robinhood|wealthfront|betterment|coinbase|vanguard|schwab|"
    r"e\*trade|etrade|fidelity|acorns|public\.com|apple savings|marcus|sofi invest|"
    r"principal|empower retirement|netbenefits)")


def classify(out_amt: float, acct_kind: str, category: str, merchant: str, bucket: str,
             peer_wallet_present: bool, txn_type: str | None = None) -> str:
    """Return kind: spend | refund | income | transfer | peer_out | peer_in | fee | cash | other_inflow.

    When the source labels the row (Origin's Type column: Expense / Income / Transfer) that label
    wins over keyword matching, which is only a fallback for exports that carry no type.
    """
    text = f"{_flat(category)} | {_flat(merchant)}"
    is_out = out_amt > 0
    t = _flat(txn_type)

    if t in EXPLICIT_TYPES:
        if t == "transfer":
            return "transfer"
        # An export may label a bank transfer or a brokerage funding row "Expense".
        # A transfer word or a known investing destination outranks that label.
        if STRONG_TRANSFER_RE.search(text):
            return "transfer"
        # Funding a peer wallet that is itself in the ledger would double count the
        # payment the wallet then makes, so the funding leg is a transfer.
        if (bucket == "peer" and acct_kind != "peer_wallet" and peer_wallet_present
                and any(w in text for w in FUNDABLE_WALLET_WORDS)):
            return "transfer"
        if t == "income":
            if is_out:
                return "transfer"  # money out labeled Income is a reversed deposit, not spending
            # Money arriving on a credit card is a merchant refund or statement credit,
            # never income, however the export labels it.
            return "refund" if acct_kind == "card" else "income"
        # Expense
        if not is_out:
            return "refund"
        if bucket == "peer" or (acct_kind == "peer_wallet" and bucket == "other"):
            return "peer_out"
        if bucket == "fees_interest":
            return "fee"
        if bucket == "cash":
            return "cash"
        return "spend"

    if bucket == "rent_housing":
        return "spend" if is_out else "other_inflow"
    if any(w in text for w in TRANSFER_WORDS):
        return "transfer"
    if ("payment" in text or "pmt" in text) and any(w in text for w in ISSUER_WORDS):
        return "transfer"
    if (bucket == "peer" and acct_kind != "peer_wallet" and peer_wallet_present
            and any(w in text for w in FUNDABLE_WALLET_WORDS)):
        return "transfer"  # funding a peer wallet that is itself in the ledger

    if is_out:
        if bucket == "peer":
            return "peer_out"
        if bucket == "fees_interest":
            return "fee"
        if bucket == "cash":
            return "cash"
        return "spend"

    if any(w in text for w in INCOME_WORDS):
        return "income"
    if acct_kind == "card":
        return "refund"
    if any(w in text for w in REFUND_WORDS):
        return "refund"
    if bucket == "peer" or acct_kind == "peer_wallet":
        return "peer_in"
    return "other_inflow"


def norm_merchant(m: str) -> str:
    t = _flat(m)
    t = re.sub(r"[#*]\s*\d+", " ", t)
    t = re.sub(r"\d+", " ", t)
    t = re.sub(r"[^a-z& ]+", " ", t)
    t = re.sub(r"\b(inc|llc|ltd|corp|co|the|new york|ny|nyc|brooklyn|manhattan|queens|online|www|com|us|usa)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return " ".join(t.split()[:3]) or (m or "").strip().lower()[:24]


# ----------------------------------------------------------------------------
# Sign convention resolution for CSV sources
# ----------------------------------------------------------------------------

def resolve_sign(rows, sign_mode="auto"):
    """rows have 'amount' (raw signed), 'type', 'dc_split'. Return (convention, note).
    Convention 'neg-out' means a negative raw amount is money out."""
    if sign_mode in ("neg-out", "pos-out"):
        return sign_mode, f"sign convention forced: {sign_mode}"
    if rows and all(r.get("dc_split") for r in rows):
        return "neg-out", "debit/credit columns found; inflow positive"
    types = {(r.get("type") or "").lower() for r in rows if r.get("type")}
    if types & {"debit", "credit", "purchase", "payment", "sale", "return"}:
        return "type-column", f"type column drives direction ({', '.join(sorted(types))[:80]})"
    if "expense" in types:
        # Origin-style Expense/Income/Transfer: read the convention off the Expense rows themselves
        # rather than counting signs across the whole file, which a flood of interest rows can skew.
        exp = [r["amount"] for r in rows if (r.get("type") or "").lower() == "expense"]
        neg_exp = sum(1 for a in exp if a < 0)
        conv = "neg-out" if neg_exp >= len(exp) - neg_exp else "pos-out"
        return conv, f"{conv} from {len(exp)} Expense rows ({neg_exp} negative)"
    neg = sum(1 for r in rows if r["amount"] < 0)
    pos = sum(1 for r in rows if r["amount"] > 0)
    if neg >= pos:
        return "neg-out", f"guessed neg-out: {neg} negative vs {pos} positive rows (spend rows usually dominate)"
    return "pos-out", f"guessed pos-out: {pos} positive vs {neg} negative rows (spend rows usually dominate)"


def outflow_amount(raw_amount: float, typ: str, convention: str) -> float:
    if convention == "type-column":
        t = (typ or "").lower()
        mag = abs(raw_amount)
        if t in ("credit", "payment", "return", "refund", "deposit"):
            return -mag
        if t in ("debit", "purchase", "sale", "withdrawal", "fee"):
            return mag
        return -raw_amount
    if convention == "pos-out":
        return raw_amount
    return -raw_amount
