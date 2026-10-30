# Finance Ledger

A local-first Python ledger that turns CSV exports into a weekly spending game.
Import idempotently, distinguish spending from transfers and refunds, build a
baseline character, and compare a recent window against it. A small HTTP receiver
can accept pending purchase events and reconcile them against later bank rows.

## Try it with synthetic data

Python 3.9+; standard library only. Run from the repository root:

```sh
export MINT_HOME="$(mktemp -d)"
python3 -m mint demo "$MINT_HOME/demo.csv"
python3 -m mint import-csv "$MINT_HOME/demo.csv" --source demo
python3 -m mint import-csv "$MINT_HOME/demo.csv" --source demo
python3 -m mint character build --name Baseline
python3 -m mint week --days 7
python3 -m mint status
```

The second import should add zero rows. The generated example transactions are
fictional. `MINT_HOME` selects the data directory; the default is `~/.mint`.
Do not commit your exports, ledger, configuration, or generated reports.

## Design

- `mint/normalize.py`: flexible CSV parsing, sign conventions, merchant categories,
  and income/transfer/refund classification
- `mint/ledger.py`: SQLite schema, content-derived identifiers, ingestion tokens,
  deduplication, pending-event reconciliation
- `mint/importers.py`: CSV ingestion
- `mint/profile.py`: aggregate reports
- `mint/character.py`: baseline scoring and weekly comparison
- `mint/serve.py`: token-protected local HTTP receiver

Use `python3 -m mint --help` for commands. To start the optional receiver:

```sh
python3 -m mint serve --host 127.0.0.1 --port 8787
```

`GET /health` is public locally; data routes require the generated ingest token
from `$MINT_HOME/config.json` in an `Authorization: Bearer ...` header. Keep the
receiver on a trusted local machine. It is not a hosted multi-user service.

## Limits

CSV ingestion and local reporting work; live bank connectors are not included.
Heuristic categorization can be wrong and should be reviewed. The scores are
configurable product heuristics, not financial advice. No operation moves money
or changes an external financial account.

## Verify

```sh
python3 -m compileall -q mint
python3 -m unittest discover -s tests -v
```

MIT licensed. This code edition contains no original private history or records.
