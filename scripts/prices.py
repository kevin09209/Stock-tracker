"""Fetch daily closing prices for every mentioned ticker.

Default source is Stooq (free, no API key): https://stooq.com/q/d/l/?s=aaoi.us&i=d
Non-US listings need a symbol override in config.price_symbols (e.g. SIVE -> sive.se).

Offline import:  python3 scripts/prices.py --import data/sample_prices.json
  JSON format: {"TICKER": {"YYYY-MM-DD": close, ...}, ...}
Online fetch:    python3 scripts/prices.py [--since YYYY-MM-DD]
"""
import argparse
import csv
import io
import json
import sys
import urllib.request

from db import connect, load_config


def stooq_symbol(ticker, cfg):
    overrides = cfg.get("price_symbols", {})
    if ticker in overrides:
        return overrides[ticker]
    return ticker.lower() + overrides.get("_default_suffix", ".us")


def fetch_stooq(symbol, since):
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    if since:
        url += f"&d1={since.replace('-', '')}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read().decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(body)))
    return [(r["Date"], float(r["Close"])) for r in rows if r.get("Close") not in (None, "", "N/A")]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--import", dest="import_file", help="匯入 JSON 價格檔（離線）")
    ap.add_argument("--since", help="只抓此日期之後（YYYY-MM-DD）")
    args = ap.parse_args()

    cfg = load_config()
    con = connect()

    if args.import_file:
        data = json.loads(open(args.import_file, encoding="utf-8").read())
        n = 0
        for ticker, series in data.items():
            for date, close in series.items():
                con.execute(
                    "INSERT OR REPLACE INTO prices(ticker, date, close) VALUES(?,?,?)",
                    (ticker, date, float(close)),
                )
                n += 1
        con.commit()
        print(f"匯入 {n} 筆價格")
        return

    tickers = [r["ticker"] for r in con.execute("SELECT DISTINCT ticker FROM mentions").fetchall()]
    ok, failed = 0, []
    for t in tickers:
        since = args.since
        if not since:
            row = con.execute("SELECT MIN(date) m FROM posts").fetchone()
            since = row["m"]
        try:
            series = fetch_stooq(stooq_symbol(t, cfg), since)
            for date, close in series:
                con.execute(
                    "INSERT OR REPLACE INTO prices(ticker, date, close) VALUES(?,?,?)",
                    (t, date, close),
                )
            con.commit()
            ok += 1
        except Exception as e:  # noqa: BLE001 - report and continue with other tickers
            failed.append(f"{t}: {e}")
    print(f"成功更新 {ok}/{len(tickers)} 檔價格")
    if failed:
        print("失敗：\n  " + "\n  ".join(failed), file=sys.stderr)


if __name__ == "__main__":
    main()
