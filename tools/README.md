# tools

## profile_sample.py

Profiles a transactions CSV export into aggregate-only numbers without touching the ledger.
Thin wrapper over `mint/profile.py`; standard library only. For the full ledger workflow use `python3 -m mint` (see the root README).

```
python3 tools/profile_sample.py ~/Downloads/origin-export.csv
python3 tools/profile_sample.py export.csv --since 2025-11-01 --accounts "amex,chase,apple card,wells"
python3 tools/profile_sample.py --demo /tmp/demo.csv          # try it on synthetic data first
```

It writes `reports/profile.md` and `reports/profile.json` (both gitignored) and
prints the Markdown. If column detection fails, pass `--map`, for example
`--map date=Date,amount=Amount,merchant=Description,category=Category,account=Account`.
If the sign guess is wrong, pass `--sign neg-out` or `--sign pos-out`.

Privacy rule: the raw export stays on disk. The report has no individual
transactions, only totals, distributions, top merchants, bills and habits. That
report is what travels into a conversation, and only if you choose to paste it.
