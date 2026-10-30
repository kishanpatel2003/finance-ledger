"""Tiny HTTP receiver for the iPhone Shortcut (and anything else that can POST JSON).

POST /ingest/wallet
  Authorization: Bearer <ingest_token from ~/.mint/config.json>
  {"amount": 12.34, "merchant": "Blue Bottle", "card": "Apple Card",
   "date": "2026-09-02T14:03:00", "category": "Food"}      # date optional (defaults to now)

GET /health -> {"ok": true}
GET /week   -> current scoreboard text (token required)
"""
from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ledger
from .normalize import parse_amount, parse_date


def _ingest_wallet(payload: dict) -> dict:
    amount = parse_amount(payload.get("amount"))
    if amount is None:
        raise ValueError("amount missing or unparseable")
    merchant = str(payload.get("merchant") or payload.get("name") or "").strip()
    card = str(payload.get("card") or payload.get("account") or "Apple Card").strip()
    category = str(payload.get("category") or "").strip()
    d, hour = parse_date(str(payload.get("date") or ""))
    if d is None:
        now = datetime.now()
        d, hour = now.date(), now.hour
    # Wallet reports purchases as positive amounts; refunds arrive negative.
    out = abs(amount) if payload.get("refund") not in (True, "true", 1) else -abs(amount)
    received = datetime.now().isoformat(timespec="seconds")
    ext = ledger.content_id("wallet", card, d.isoformat(), hour, round(out, 2), merchant, received)
    with ledger.connect() as con:
        aid = ledger.get_or_create_account(con, card, "wallet_shortcut", institution="Apple Wallet")
        inserted = ledger.upsert_transaction(con, account_id=aid, d=d, hour=hour, out=out, merchant=merchant,
                                             category_src=category, source="wallet_shortcut", external_id=ext,
                                             raw=payload, pending=1)
        con.commit()
    return {"ok": True, "inserted": inserted, "account": card, "date": d.isoformat(), "out": out}


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authed(self):
            auth = self.headers.get("Authorization", "")
            return auth == f"Bearer {token}" or self.headers.get("X-Mint-Token", "") == token

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            if self.path.startswith("/week"):
                from .cli import week_text
                try:
                    return self._send(200, week_text(), ctype="text/plain; charset=utf-8")
                except Exception as e:  # noqa: BLE001
                    return self._send(500, {"error": str(e)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            if self.path != "/ingest/wallet":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("body must be a JSON object")
                return self._send(200, _ingest_wallet(payload))
            except Exception as e:  # noqa: BLE001
                return self._send(400, {"error": str(e)})

        def log_message(self, fmt, *args):  # keep merchant names out of server logs
            pass

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8787):
    cfg = ledger.init_home()
    httpd = ThreadingHTTPServer((host, port), make_handler(cfg["ingest_token"]))
    print(f"mint serve listening on {host}:{port}  (token in {ledger.config_path()})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
