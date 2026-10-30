# Finance Ledger

A local-first Python ledger that turns CSV exports into a weekly spending game. Import transactions idempotently, separate spending from transfers and refunds, build a baseline character, and compare a recent window against it. An HTTP receiver accepts pending purchase events and reconciles them against later bank rows.

## Quick start

Python 3.9+; standard library only. Run from the repository root:

```sh
export MINT_HOME="$(mktemp -d)"
python3 -m mint example "$MINT_HOME/example.csv"
python3 -m mint import-csv "$MINT_HOME/example.csv" --source example
python3 -m mint import-csv "$MINT_HOME/example.csv" --source example
python3 -m mint character build --name Baseline
python3 -m mint week --days 7
python3 -m mint status
```

This creates example transactions in an isolated store. The second import adds zero rows. For your own data, import a CSV export instead. `MINT_HOME` selects storage; the default is `~/.mint`.

## Design

- `mint/normalize.py`: CSV parsing, sign conventions, merchant categories, and income/transfer/refund classification
- `mint/ledger.py`: SQLite storage, content-derived identifiers, deduplication, and pending-event reconciliation
- `mint/importers.py`: CSV ingestion
- `mint/profile.py`: aggregate reports
- `mint/character.py`: baseline scoring and weekly comparison
- `mint/serve.py`: token-protected local HTTP receiver

Use `python3 -m mint --help` for commands. To start the receiver:

```sh
python3 -m mint serve --host 127.0.0.1 --port 8787
```

`GET /health` is open locally. Data routes require the ingest token from `$MINT_HOME/config.json` in an `Authorization: Bearer ...` header. The receiver is designed for a trusted local machine.

## Data

The ledger uses local CSV imports; bank connectors are not included. Categorization and scoring use configurable heuristics. Review imported categories and keep exports, configuration, and reports outside Git.

## Tests

```sh
python3 -m compileall -q mint
python3 -m unittest discover -s tests -v
```

[MIT](LICENSE)
