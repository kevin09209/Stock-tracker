"""Generate the daily zh-Hant HTML report.

Usage: python3 scripts/report.py [--date YYYY-MM-DD] [--out DIR]
Defaults: date = latest post date in DB; out = reports/
Output:   reports/{handle}-tracker-{date}-zh.html
"""
import argparse
import html
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest import HORIZONS, compute_calls, scorecard
from db import ROOT, account_display, close_on_or_before, connect, get_accounts, load_config

STANCE_ZH = {"bull": "多", "bear": "空", "neutral": "中"}


def day_offset(date, days):
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def pct(a, b):
    if a is None or b is None or a == 0:
        return None
    return (b / a - 1) * 100


def fmt_pct(v, signed=True):
    if v is None:
        return '<span class="na">—</span>'
    cls = "up" if v > 0 else ("down" if v < 0 else "flat")
    sign = "+" if (signed and v > 0) else ""
    return f'<span class="{cls}">{sign}{v:.1f}%</span>'


def gather(con, cfg, date):
    """Aggregate per-ticker stats for the report date."""
    d7, d28, d90 = day_offset(date, -6), day_offset(date, -27), day_offset(date, -89)
    rows = con.execute(
        """
        SELECT m.ticker,
               SUM(CASE WHEN p.date = :d THEN 1 ELSE 0 END)  AS today,
               SUM(CASE WHEN p.date >= :d7 AND p.date <= :d THEN 1 ELSE 0 END) AS last7,
               SUM(CASE WHEN p.date >= :d28 AND p.date <= :d THEN 1 ELSE 0 END) AS last28,
               SUM(CASE WHEN p.date >= :d90 AND p.date <= :d THEN 1 ELSE 0 END) AS last90,
               COUNT(*) AS total,
               MIN(p.date) AS first_date,
               MAX(CASE WHEN p.date <= :d THEN p.date END) AS last_date
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE p.date <= :d
        GROUP BY m.ticker
        """,
        {"d": date, "d7": d7, "d28": d28, "d90": d90},
    ).fetchall()

    tickers = []
    for r in rows:
        t = dict(r)
        ticker = t["ticker"]
        stances = con.execute(
            """
            SELECT m.stance, COUNT(*) c FROM mentions m JOIN posts p ON p.id = m.post_id
            WHERE m.ticker = ? AND p.date = ? GROUP BY m.stance
            """,
            (ticker, date),
        ).fetchall()
        t["today_stance"] = {s["stance"]: s["c"] for s in stances}

        t["today_accounts"] = [
            r2["account"]
            for r2 in con.execute(
                """
                SELECT DISTINCT p.account FROM mentions m JOIN posts p ON p.id = m.post_id
                WHERE m.ticker = ? AND p.date = ? ORDER BY p.account
                """,
                (ticker, date),
            ).fetchall()
        ]

        # overall stance across the whole tracked window (for the market summary)
        overall = con.execute(
            """
            SELECT m.stance, COUNT(*) c FROM mentions m JOIN posts p ON p.id = m.post_id
            WHERE m.ticker = ? AND p.date <= ? GROUP BY m.stance
            """,
            (ticker, date),
        ).fetchall()
        counts = {s["stance"]: s["c"] for s in overall}
        bull, bear = counts.get("bull", 0), counts.get("bear", 0)
        t["net"] = "bull" if bull > bear else ("bear" if bear > bull else "neutral")

        t["first_close"], _ = close_on_or_before(con, ticker, t["first_date"])
        t["last_close"], _ = close_on_or_before(con, ticker, t["last_date"] or date)
        t["change_since_first"] = pct(t["first_close"], t["last_close"])

        prev_close, _ = close_on_or_before(con, ticker, day_offset(date, -1))
        today_close, today_close_date = close_on_or_before(con, ticker, date)
        t["day_change"] = pct(prev_close, today_close) if today_close_date == date else None
        tickers.append(t)
    return tickers


def gather_consensus(con, date):
    """Per-(ticker, account) net stance over the trailing 7 days, for tickers
    that at least two tracked accounts discussed in that window."""
    d7 = day_offset(date, -6)
    rows = con.execute(
        """
        SELECT m.ticker, p.account,
               SUM(m.stance='bull') b, SUM(m.stance='bear') s, COUNT(*) n
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE p.date BETWEEN ? AND ?
        GROUP BY m.ticker, p.account
        """,
        (d7, date),
    ).fetchall()
    by_ticker = {}
    for r in rows:
        net = "bull" if r["b"] > r["s"] else ("bear" if r["s"] > r["b"] else "neutral")
        by_ticker.setdefault(r["ticker"], []).append((r["account"], net, r["n"]))
    return {t: v for t, v in by_ticker.items() if len(v) >= 2}


def stance_line(today_stance):
    parts = [f'{today_stance.get(k, 0)}{STANCE_ZH[k]}' for k in ("bull", "bear", "neutral") if today_stance.get(k)]
    if parts:
        return " ".join(parts)
    if today_stance.get("background"):
        return "無（僅背景提及）"
    return "無"


def currency_prefix(ticker, cfg):
    cur = cfg.get("currencies", {}).get(ticker, cfg.get("currencies", {}).get("_default", ""))
    return (cur + " ") if cur else ""


NET_ZH = {"bull": ("看多", "up"), "bear": ("看空", "down"), "neutral": ("中性", "flat")}


def scorecard_html(card, display, esc):
    if not card:
        return ""
    rows = []
    for acct, s in sorted(card.items(), key=lambda kv: -kv[1]["n_calls"]):
        cells = []
        for h in HORIZONS:
            st = s["horizons"].get(h)
            if st:
                cls = "up" if st["avg"] > 0 else ("down" if st["avg"] < 0 else "flat")
                cells.append(
                    f'<td class="mono">命中 {st["hit"]:.0f}%<br>'
                    f'<span class="{cls}">均 {st["avg"]:+.1f}%</span> <span class="na">(n={st["n"]})</span></td>'
                )
            else:
                cells.append('<td class="mono na">樣本不足</td>')
        rows.append(
            f'<tr><td>{esc(display.get(acct, acct))}</td>'
            f'<td class="mono">{s["n_calls"]}</td>{"".join(cells)}</tr>'
        )
    header = "".join(f"<th>{h}日</th>" for h in HORIZONS)
    return f"""
  <section>
    <h2>博主戰績記分卡</h2>
    <p class="note">只回測明確看多／看空表態（中性與背景提及不計）；報酬以博主方向計，看空時下跌為正；
    基準＝表態日（或其前最近交易日）收盤；未到期或缺價樣本不計。過去戰績不代表未來。</p>
    <div class="tablewrap">
      <table>
        <thead><tr><th>博主</th><th>明確表態</th>{header}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </section>"""


def render(cfg, date, tickers, consensus, card, local_now):
    accounts = get_accounts(cfg)
    display = account_display(cfg)
    multi = len(accounts) > 1
    title = "多博主追蹤日報" if multi else f"{accounts[0]['display']} 追蹤日報"
    esc = html.escape
    today_tickers = [t for t in tickers if t["today"] > 0]
    today_tickers.sort(key=lambda t: -t["today"])
    n_tickers_today = len(today_tickers)
    n_mentions_today = sum(t["today"] for t in today_tickers)

    opinionated = [t for t in tickers if t["net"] != "neutral" or True]
    bulls = sum(1 for t in tickers if t["net"] == "bull")
    bears = sum(1 for t in tickers if t["net"] == "bear")
    denom = len(tickers) or 1
    bull_pct, bear_pct = round(bulls / denom * 100), round(bears / denom * 100)

    min90 = cfg["report"].get("quarterly_table_min_mentions_90d", 3)
    table_rows = sorted(
        (t for t in tickers if t["last90"] >= min90),
        key=lambda t: -t["total"],
    )
    cards = today_tickers[: cfg["report"].get("top_cards_limit", 8)]
    industries = cfg.get("industries", {})

    card_html = []
    for t in cards:
        tk = t["ticker"]
        cur = currency_prefix(tk, cfg)
        who = ""
        if multi:
            names = "、".join(display.get(a, a) for a in t["today_accounts"])
            who = f'<div class="meta">提及博主：{esc(names)}</div>'
        card_html.append(f"""
      <div class="card">
        <div class="card-head">
          <span class="ticker">{esc(tk)}</span>
          {f'<span class="cur">{esc(cur.strip())}</span>' if cur else ''}
          <span class="daychg">較上一交易日 {fmt_pct(t["day_change"])}</span>
        </div>
        <div class="bignum">當天提及 <b>{t["today"]}</b> 次 <span class="sub">・7日內 {t["last7"]} ・28日內 {t["last28"]}</span></div>
        <div class="meta">今日表態：{esc(stance_line(t["today_stance"]))}</div>
        {who}
        <div class="meta">首提 {esc(t["first_date"])}</div>
      </div>""")

    consensus_html = ""
    if multi and consensus:
        items = []
        for tk in sorted(consensus, key=lambda k: -len(consensus[k])):
            entries = consensus[tk]
            nets = {net for _, net, _ in entries}
            if nets == {"bull"}:
                verdict, vcls = "一致看多", "up"
            elif nets == {"bear"}:
                verdict, vcls = "一致看空", "down"
            elif "bull" in nets and "bear" in nets:
                verdict, vcls = "多空分歧", "flat"
            elif "bull" in nets:
                verdict, vcls = "偏多", "up"
            elif "bear" in nets:
                verdict, vcls = "偏空", "down"
            else:
                verdict, vcls = "皆中性", "flat"
            chips = "・".join(
                f'{esc(display.get(a, a))} <span class="{NET_ZH[net][1]}">{NET_ZH[net][0]}</span>（{n}次）'
                for a, net, n in entries
            )
            items.append(
                f'<div class="consensus-row"><span class="ticker">{esc(tk)}</span>'
                f'<span class="verdict {vcls}">{verdict}</span><span class="chips">{chips}</span></div>'
            )
        consensus_html = f"""
  <section>
    <h2>博主共識（近7日，≥2 位博主提及）</h2>
    <p class="note">各博主以近7日提及的淨表態計；「一致看多／看空」僅代表觀點重疊，不代表正確。</p>
    <div class="summary">{''.join(items)}</div>
  </section>"""

    row_html = []
    for t in table_rows:
        tk = t["ticker"]
        cur = currency_prefix(tk, cfg)

        def price_cell(date_, close):
            if close is None:
                return f'{esc(date_ or "—")}<br><span class="na">—</span>'
            return f'{esc(date_)}<br><span class="price">{esc(cur)}{close:,.2f}</span>'

        chg = t["change_since_first"]
        row_html.append(f"""
        <tr>
          <td class="mono"><a class="tk" href="tickers/{esc(tk)}-zh.html">{esc(tk)}</a></td>
          <td>{esc(industries.get(tk, "（-）"))}</td>
          <td class="mono" data-v="{t['first_date']}">{price_cell(t["first_date"], t["first_close"])}</td>
          <td class="mono" data-v="{t['last_date'] or ''}">{price_cell(t["last_date"], t["last_close"])}</td>
          <td class="mono" data-v="{chg if chg is not None else -10**9}">{fmt_pct(chg)}</td>
          <td class="mono" data-v="{t['total']}">{t["total"]}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} {esc(date)}</title>
<style>
  :root {{
    --bg:#faf8f4; --card:#ffffff; --ink:#26241f; --muted:#8a8578;
    --line:#e8e3d8; --accent:#b08d57; --up:#1a7f4b; --down:#c04545;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif; line-height:1.6; }}
  .wrap {{ max-width:880px; margin:0 auto; padding:32px 20px 64px; }}
  .mono, .price, .bignum b {{ font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }}
  header h1 {{ font-size:26px; margin:0 0 4px; }}
  .datebadge {{ display:inline-block; background:#3f4a3f; color:#e8f0e4; padding:2px 12px;
                border-radius:4px; font-family:ui-monospace,Menlo,monospace; font-size:15px; }}
  .stats {{ color:var(--muted); margin:10px 0 0; font-size:14px; }}
  section {{ margin-top:36px; }}
  h2 {{ font-size:17px; border-left:4px solid var(--accent); padding-left:10px; margin:0 0 6px; }}
  .note {{ color:var(--muted); font-size:13px; margin:0 0 14px; }}
  .summary {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }}
  .gaugebar {{ height:10px; border-radius:6px; overflow:hidden; display:flex; margin:8px 0 10px; }}
  .gaugebar i {{ display:block; height:100%; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:14px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card-head {{ display:flex; align-items:baseline; gap:8px; }}
  .ticker {{ font-size:20px; font-weight:700; font-family:ui-monospace,Menlo,monospace; }}
  .cur {{ font-size:11px; color:var(--muted); border:1px solid var(--line); border-radius:3px; padding:0 4px; }}
  .daychg {{ margin-left:auto; font-size:13px; }}
  .bignum {{ margin-top:8px; font-size:14px; }}
  .bignum b {{ font-size:26px; }}
  .sub, .meta {{ color:var(--muted); font-size:13px; }}
  .meta {{ margin-top:2px; }}
  .up {{ color:var(--up); }} .down {{ color:var(--down); }} .flat, .na {{ color:var(--muted); }}
  a.tk {{ color:inherit; text-decoration:none; border-bottom:1px dashed var(--muted); }}
  a.tk:hover {{ border-bottom-style:solid; }}
  .consensus-row {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:10px; padding:8px 0; border-bottom:1px solid var(--line); }}
  .consensus-row:last-child {{ border-bottom:none; }}
  .consensus-row .ticker {{ font-size:16px; min-width:64px; }}
  .verdict {{ font-weight:700; }}
  .chips {{ color:var(--muted); font-size:13px; }}
  .tablewrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; min-width:640px; }}
  th, td {{ text-align:left; padding:10px 14px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ cursor:pointer; user-select:none; white-space:nowrap; color:var(--muted); font-weight:600; }}
  th .arrow {{ font-size:10px; }}
  tr:last-child td {{ border-bottom:none; }}
  footer {{ margin-top:48px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:16px; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#191813; --card:#211f19; --ink:#e9e5da; --muted:#98917f;
             --line:#37342b; --up:#4dbd85; --down:#e07070; }}
    .datebadge {{ background:#2d382d; color:#cfe3c8; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{esc(title)} <span class="datebadge">{esc(date)} ET</span></h1>
    <p class="stats">追蹤：{esc("、".join(f"{a['display']}（@{a['handle']}）" for a in accounts))}<br>
    今日 {n_tickers_today} 檔標的 ・ {n_mentions_today} 次提及<br>
    數據更新：美東 {esc(date)} ・ 本地時間：{esc(local_now)}</p>
  </header>
{consensus_html}

  <section>
    <h2>市場標籤（看多／看空／中性）</h2>
    <div class="summary">
      <div>按標的數：淨看多 <b class="up">{bull_pct}%</b> ・ 淨看空 <b class="down">{bear_pct}%</b>（追蹤 {len(tickers)} 檔）</div>
      <div class="gaugebar">
        <i style="width:{bull_pct}%;background:var(--up)"></i>
        <i style="width:{max(0, 100 - bull_pct - bear_pct)}%;background:var(--line)"></i>
        <i style="width:{bear_pct}%;background:var(--down)"></i>
      </div>
      <div class="note">統計口徑：博主在推文中表達的看多／看空／中性表態，按標的數彙總；未含權重，僅提及不計方向。</div>
    </div>
  </section>

  <section>
    <h2>今天重點討論的標的（按當天提及量）</h2>
    <p class="note">7日／28日＝滾動窗口累計提及次數；表態為當日推文口徑。</p>
    <div class="cards">{''.join(card_html) or '<p class="note">今日無提及。</p>'}</div>
  </section>

  <section>
    <h2>季度全標的表</h2>
    <p class="note">點欄位標題可排序；收錄近90日 ≥{min90} 次提及者；行業（-）＝未分類；
    漲幅＝首次提及日收盤 → 最近提及日收盤。</p>
    <div class="tablewrap">
      <table id="qt">
        <thead><tr>
          <th data-k="0">代碼 <span class="arrow"></span></th>
          <th data-k="1">行業 <span class="arrow"></span></th>
          <th data-k="2">首次提及 <span class="arrow"></span></th>
          <th data-k="3">最近提及 <span class="arrow"></span></th>
          <th data-k="4">漲幅 <span class="arrow"></span></th>
          <th data-k="5">提及次數 <span class="arrow">▼</span></th>
        </tr></thead>
        <tbody>{''.join(row_html)}</tbody>
      </table>
    </div>
  </section>
{scorecard_html(card, display, esc)}
  <footer>
    本報告由自動化工具彙整 {esc("、".join(f"{a['display']}（@{a['handle']}）" for a in accounts))} 公開貼文而成，
    與其本人無任何關聯，亦不構成投資建議——僅為方便研究。內容可能有誤，請以原帖為準並自行核實（DYOR）。
  </footer>
</div>
<script>
(function () {{
  var tbl = document.getElementById('qt'), dir = {{}};
  tbl.querySelectorAll('th').forEach(function (th) {{
    th.addEventListener('click', function () {{
      var k = +th.dataset.k, rows = [].slice.call(tbl.tBodies[0].rows);
      dir[k] = -(dir[k] || (k >= 4 ? 1 : -1));
      rows.sort(function (a, b) {{
        var av = a.cells[k].dataset.v ?? a.cells[k].textContent.trim();
        var bv = b.cells[k].dataset.v ?? b.cells[k].textContent.trim();
        var an = parseFloat(av), bn = parseFloat(bv);
        var c = (!isNaN(an) && !isNaN(bn)) ? an - bn : String(av).localeCompare(String(bv));
        return dir[k] * c;
      }});
      rows.forEach(function (r) {{ tbl.tBodies[0].appendChild(r); }});
      tbl.querySelectorAll('.arrow').forEach(function (s) {{ s.textContent = ''; }});
      th.querySelector('.arrow').textContent = dir[k] > 0 ? '▲' : '▼';
    }});
  }});
}})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="報告日期（預設＝資料庫最新貼文日）")
    ap.add_argument("--out", default=str(ROOT / "reports"), help="輸出目錄")
    args = ap.parse_args()

    cfg = load_config()
    con = connect()
    date = args.date or con.execute("SELECT MAX(date) m FROM posts").fetchone()["m"]
    if not date:
        raise SystemExit("資料庫沒有貼文，請先執行 scripts/fetch.py")

    tickers = gather(con, cfg, date)
    consensus = gather_consensus(con, date)
    card = scorecard(compute_calls(con))
    local_now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    accounts = get_accounts(cfg)
    slug = accounts[0]["handle"] if len(accounts) == 1 else "multi"
    out = out_dir / f"{slug}-tracker-{date}-zh.html"
    out.write_text(render(cfg, date, tickers, consensus, card, local_now), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
