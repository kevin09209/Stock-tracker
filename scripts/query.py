"""Dump one ticker's full mention history as Markdown, for deep-dive analysis.

This is the input Claude uses to write the 「觀點分析」（叙事弧線＋關鍵觀點）section.

Usage: python3 scripts/query.py TICKER [--limit N]
"""
import argparse
import signal

from db import account_display, close_on_or_before, connect, load_config

if hasattr(signal, "SIGPIPE"):  # exit quietly when piped into `head`
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

STANCE_ZH = {"bull": "看多", "bear": "看空", "neutral": "中性", "background": "背景提及"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ticker")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    ticker = args.ticker.upper()

    cfg = load_config()
    con = connect()
    display = account_display(cfg)
    rows = con.execute(
        """
        SELECT p.date, p.text, p.url, p.account, m.stance
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE m.ticker = ? ORDER BY p.date, p.ts LIMIT ?
        """,
        (ticker, args.limit),
    ).fetchall()
    if not rows:
        raise SystemExit(f"資料庫中沒有 {ticker} 的提及紀錄")

    counts = {}
    for r in rows:
        counts[r["stance"]] = counts.get(r["stance"], 0) + 1
    first, last = rows[0]["date"], rows[-1]["date"]
    fc, _ = close_on_or_before(con, ticker, first)
    lc, _ = close_on_or_before(con, ticker, last)
    cur = cfg.get("currencies", {}).get(ticker, "")

    by_account = {}
    for r in rows:
        by_account[r["account"]] = by_account.get(r["account"], 0) + 1

    print(f"# {ticker} — 提及全紀錄")
    print(f"\n追蹤期：{first} 至 {last} ・ 共 {len(rows)} 次提及")
    print("提及博主：" + " ・ ".join(f"{display.get(a, a)} {n}次" for a, n in sorted(by_account.items())))
    print("表態分佈：" + " ・ ".join(f"{STANCE_ZH[k]} {v}" for k, v in sorted(counts.items())))
    if fc and lc:
        print(f"價格：首提日收盤 {cur}{fc:,.2f} → 最近提及日收盤 {cur}{lc:,.2f}（{(lc / fc - 1) * 100:+.1f}%）")
    print("\n---\n")
    for r in rows:
        print(f"## {r['date']} {display.get(r['account'], r['account'])}（{STANCE_ZH[r['stance']]}）")
        if r["url"]:
            print(r["url"])
        print(f"\n> {r['text'].strip()}\n")


if __name__ == "__main__":
    main()
