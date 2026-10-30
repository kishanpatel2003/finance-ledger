# tools

## profile_sample.py

Profiles a transactions CSV export into aggregate-only numbers without touching the ledger.
Thin wrapper over `mint/profile.py`; standard library only. For the full ledger workflow use `python3 -m mint` (see the root README).

```
python3 tools/profile_sample.py ~/Downloads/origin-export.csv
python3 tools/profile_sample.py export.csv --since 2025-11-01 --accounts "amex,chase,apple card,wells"
python3 tools/profile_sample.py --demo /tmp/example.csv       # create and profile example transactions
```

It writes `reports/profile.md` and `reports/profile.json` (both gitignored) and
prints the Markdown. If column detection fails, pass `--map`, for example
`--map date=Date,amount=Amount,merchant=Description,category=Category,account=Account`.
If the sign guess is wrong, pass `--sign neg-out` or `--sign pos-out`.

Raw exports stay on disk. Reports contain totals, distributions, top merchants, bills, and habits rather than individual transactions.
