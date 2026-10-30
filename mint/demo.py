"""Generate example transactions for the ledger."""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta


def write_demo(path, days=300, seed=7):
    rng = random.Random(seed)
    end = date.today()
    start = end - timedelta(days=days - 1)
    rows = []

    def add(d, desc, cat, amt, acct):
        rows.append([d.isoformat(), desc, cat, f"{amt:.2f}", acct])

    checking, amex, chase, apple, venmo = ("Wells Fargo Clear Access Checking", "Amex Gold", "Chase Freedom Unlimited",
                                           "Apple Card", "Venmo")
    coffee = ["Blue Bottle Coffee", "Starbucks #1123", "Devocion", "Variety Coffee Roasters", "Dunkin #3021"]
    lunch = ["Sweetgreen", "Cava", "Chipotle Online", "Just Salad", "Dig", "Los Tacos No. 1", "Xi'an Famous Foods"]
    dinner = ["Carbone", "Via Carota", "Thai Villa", "Ippudo NY", "Cote Korean Steakhouse", "Joe's Pizza", "Lucali", "Raku", "Mamoun's"]
    bars = ["Ray's Bar", "The Dead Rabbit", "Skinny Dennis", "Attaboy", "Union Pool", "Dante NYC"]
    delivery = ["DoorDash", "Uber Eats", "Grubhub Seamless", "Caviar"]
    ride = ["Uber Trip", "Lyft Ride", "OMNI MTA NYC"]
    shop = ["Amazon.com", "Uniqlo Soho", "Target", "Nike NYC", "Apple Store Fifth Ave", "SSENSE", "IKEA Brooklyn", "Best Buy"]
    grocery = ["Trader Joe's #552", "Whole Foods Market", "Key Food", "H Mart"]
    subs = [("Netflix.com", 15.49, chase, 3), ("Apple.com/bill iCloud", 2.99, apple, 5), ("OpenAI ChatGPT Subscr", 20.00, chase, 12),
            ("NYTimes Digital", 4.00, chase, 18), ("Equinox Membership", 235.00, amex, 1), ("Spotify Premium", 11.99, apple, 9),
            ("Google One Storage", 2.99, chase, 22), ("Citi Bike Annual", 219.00, chase, None)]

    d = start
    while d <= end:
        dow = d.weekday()
        if dow == 4 and ((d - start).days // 7) % 2 == 0:
            add(d, "EXAMPLE COMPANY PAYROLL DIRECT DEP", "Paycheck", 3350.00, checking)
        if d.day == 1:
            add(d, "Bilt Rent - Apt 4B", "Rent", -2650.00, checking)
            add(d, "ROBINHOOD ACH TRANSFER", "Transfer", -400.00, checking)
            add(d, "M1 FINANCE INVEST", "Investment", -300.00, checking)
        if d.day == 15:
            add(d, "APPLE SAVINGS TRANSFER", "Transfer", -500.00, checking)
        if d.day == 20:
            add(d, "CHASE CREDIT CRD AUTOPAY", "Credit Card Payment", -rng.uniform(700, 1400), checking)
            add(d, "AMEX EPAYMENT ACH PMT", "Credit Card Payment", -rng.uniform(900, 1900), checking)
            add(d, "Payment Thank You - Web", "Payment", rng.uniform(700, 1400), chase)
            add(d, "AUTOPAY PAYMENT - THANK YOU", "Payment", rng.uniform(900, 1900), amex)
        if d.day == 25:
            add(d, "Con Edison", "Utilities", -rng.uniform(55, 140), chase)
            add(d, "Verizon Wireless", "Utilities", -95.00, chase)
        for desc, amt, acct, day in subs:
            if day and d.day == day:
                add(d, desc, "Subscriptions", -amt, acct)
            if day is None and d.month == 3 and d.day == 14:
                add(d, desc, "Subscriptions", -amt, acct)
        if dow < 5 and rng.random() < 0.85:
            add(d, rng.choice(coffee), "Coffee Shops", -rng.choice([4.75, 5.50, 6.25, 7.10, 8.40]), apple)
        if dow < 5 and rng.random() < 0.7:
            add(d, rng.choice(lunch), "Restaurants", -rng.uniform(13, 21), amex)
        if rng.random() < (0.55 if dow >= 4 else 0.3):
            add(d, rng.choice(dinner), "Restaurants", -rng.uniform(28, 140), amex)
        if rng.random() < (0.45 if dow < 5 else 0.3):
            add(d, rng.choice(delivery), "Food Delivery", -rng.uniform(22, 48), apple)
        if rng.random() < (0.35 if dow < 5 else 0.6):
            r = rng.choice(ride)
            add(d, r, "Transportation", -(2.90 if "MTA" in r else rng.uniform(11, 38)), chase if "MTA" in r else apple)
        if dow in (4, 5) and rng.random() < 0.6:
            add(d, rng.choice(bars), "Bars & Nightlife", -rng.uniform(35, 160), amex)
            if rng.random() < 0.5:
                add(d, "Uber Trip", "Transportation", -rng.uniform(18, 45), apple)
        if dow == 6 and rng.random() < 0.8:
            add(d, rng.choice(grocery), "Groceries", -rng.uniform(45, 110), amex)
        if rng.random() < 0.09:
            add(d, rng.choice(shop), "Shopping", -rng.uniform(25, 260), chase)
        if rng.random() < 0.012:
            add(d, rng.choice(shop), "Shopping", -rng.uniform(300, 900), chase)
        if rng.random() < 0.18:
            add(d, "Venmo payment to friend", "Peer", -rng.uniform(15, 120), venmo)
        if rng.random() < 0.10:
            add(d, "Venmo payment from friend", "Peer", rng.uniform(10, 90), venmo)
        if rng.random() < 0.05:
            add(d, "VENMO CASHOUT", "Transfer", -rng.uniform(50, 200), checking)
        if rng.random() < 0.02:
            add(d, "Amazon.com Refund", "Shopping", rng.uniform(15, 80), chase)
        if rng.random() < 0.015:
            add(d, "ATM WITHDRAWAL 0231", "Cash", -rng.choice([40, 60, 100]), checking)
        d += timedelta(days=1)
    t = start + timedelta(days=int(days * 0.6))
    add(t, "JetBlue Airways", "Travel", -318.40, chase)
    add(t + timedelta(days=1), "Airbnb", "Travel", -412.00, chase)
    add(t + timedelta(days=2), "Delta Air Lines", "Travel", -286.10, chase)
    add(start + timedelta(days=int(days * 0.3)), "LATE FEE", "Fees & Charges", -29.00, chase)
    add(start + timedelta(days=int(days * 0.3)), "INTEREST CHARGE ON PURCHASES", "Fees & Charges", -41.17, chase)
    add(start + timedelta(days=45), "APPLE SAVINGS INTEREST PAID", "Interest", 12.40, checking)
    rows.sort(key=lambda r: r[0])
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["Date", "Description", "Category", "Amount", "Account"])
        wr.writerows(rows)
    return len(rows)
