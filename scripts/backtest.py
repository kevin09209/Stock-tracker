"""Backtest every explicit bull/bear call and build a per-analyst scorecard.

A "call" is one (analyst, ticker, date, stance) with stance bull or bear
(neutral/background mentions are not calls). For each call we measure the
forward return at +7/+30/+90 calendar days, signed by the call's direction
(a bear call profits when the price falls). Horizons that extend past the
latest known price, or where no newer close exists yet, are excluded (未到期).

Entry price = close on or before the call date. CLI prints the scorecard:
  python3 scripts/backtest.py [--horizon 7 30 90]
"""
import argparse
import signal
from datetime import datetime, timedelta

from db import account_display, close_on_or_before, connect, load_config

if hasattr(signal, "SIGPIPE"):  # exit quietly when piped into `head`
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

HORIZONS = (7, 30, 90)


def day_offset(date, days):
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def compute_calls(con, horizons=HORIZONS):
    rows = con.execute(
        """
        SELECT DISTINCT p.account, m.ticker, p.date, m.stance
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE m.stance IN ('bull', 'bear')
        ORDER BY p.date
        """
    ).fetchall()
    calls = []
    for r in rows:
        ticker = r["ticker"]
        entry, entry_date = close_on_or_before(con, ticker, r["date"])
        if entry is None:
            continue
        last = con.execute(
            "SELECT MAX(date) m FROM prices WHERE ticker=?", (ticker,)
        ).fetchone()["m"]
        returns = {}
        for h in horizons:
            target = day_offset(r["date"], h)
            if target > last:
                returns[h] = None  # 未到期
                continue
            px, px_date = close_on_or_before(con, ticker, target)
            if px is None or px_date <= entry_date:
                returns[h] = None  # 無更新的價格資料
                continue
            raw = (px / entry - 1) * 100
            returns[h] = raw if r["stance"] == "bull" else -raw
        calls.append(
            {
                "account": r["account"],
                "ticker": ticker,
                "date": r["date"],
                "stance": r["stance"],
                "entry": entry,
                "returns": returns,
            }
        )
    return calls


def scorecard(calls, horizons=HORIZONS):
    """-> {account: {"n_calls": int, horizons: {h: {"n","hit","avg"}}}}"""
    out = {}
    for c in calls:
        acct = out.setdefault(c["account"], {"n_calls": 0, "horizons": {h: [] for h in horizons}})
        acct["n_calls"] += 1
        for h in horizons:
            if c["returns"].get(h) is not None:
                acct["horizons"][h].append(c["returns"][h])
    for acct in out.values():
        stats = {}
        for h, rets in acct["horizons"].items():
            if rets:
                stats[h] = {
                    "n": len(rets),
                    "hit": sum(1 for r in rets if r > 0) / len(rets) * 100,
                    "avg": sum(rets) / len(rets),
                }
            else:
                stats[h] = None
        acct["horizons"] = stats
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon", type=int, nargs="+", default=list(HORIZONS))
    args = ap.parse_args()

    cfg = load_config()
    display = account_display(cfg)
    con = connect()
    calls = compute_calls(con, tuple(args.horizon))
    card = scorecard(calls, tuple(args.horizon))

    print("# 博主戰績記分卡（報酬以博主方向計；看空時下跌為正）\n")
    for acct, s in sorted(card.items()):
        print(f"## {display.get(acct, acct)}（明確表態 {s['n_calls']} 檔次）")
        for h, st in s["horizons"].items():
            if st:
                print(f"  {h:>3}日：命中 {st['hit']:.0f}% ・ 平均 {st['avg']:+.1f}%（樣本 {st['n']}）")
            else:
                print(f"  {h:>3}日：樣本不足")
        print()
    print("逐筆明細：")
    for c in calls:
        rs = " ".join(
            f"{h}日 {c['returns'][h]:+.1f}%" if c["returns"][h] is not None else f"{h}日 —"
            for h in args.horizon
        )
        print(f"  {c['date']} {display.get(c['account'], c['account'])} "
              f"{'看多' if c['stance'] == 'bull' else '看空'} {c['ticker']:<5} {rs}")


if __name__ == "__main__":
    main()
