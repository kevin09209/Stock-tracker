"""Generate one detail page per mentioned ticker: price chart with mention
markers (colored by stance), backtest stats, narrative analysis, and the full
mention timeline.

The narrative section embeds data/analysis/{TICKER}-zh.md when that file
exists — Claude writes it from `scripts/query.py TICKER` output (see SKILL.md).

Usage: python3 scripts/detail.py [--out DIR] [--tickers SIVE LITE ...]
Output: {out}/tickers/{TICKER}-zh.html   (default out = reports/)
"""
import argparse
import html
import re
from datetime import datetime
from pathlib import Path

from backtest import HORIZONS, compute_calls
from db import ROOT, account_display, close_on_or_before, connect, get_accounts, load_config

STANCE_ZH = {"bull": "看多", "bear": "看空", "neutral": "中性", "background": "背景提及"}
STANCE_COLOR = {"bull": "var(--up)", "bear": "var(--down)", "neutral": "var(--accent)", "background": "var(--muted)"}


def md_to_html(md):
    """Tiny Markdown subset: #/##/### headings, ---, > quotes, - lists, **bold**."""
    out, in_ul, in_bq = [], False, False

    def close_blocks():
        nonlocal in_ul, in_bq
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_bq:
            out.append("</blockquote>")
            in_bq = False

    def inline(s):
        s = html.escape(s)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    for line in md.splitlines():
        s = line.strip()
        if not s:
            close_blocks()
        elif s.startswith("###"):
            close_blocks(); out.append(f"<h4>{inline(s[3:].strip())}</h4>")
        elif s.startswith("##"):
            close_blocks(); out.append(f"<h3>{inline(s[2:].strip())}</h3>")
        elif s.startswith("#"):
            close_blocks(); out.append(f"<h2>{inline(s[1:].strip())}</h2>")
        elif s in ("---", "***"):
            close_blocks(); out.append("<hr>")
        elif s.startswith(">"):
            if not in_bq:
                close_blocks(); out.append("<blockquote>"); in_bq = True
            out.append(inline(s[1:].strip()) + "<br>")
        elif s.startswith("- "):
            if not in_ul:
                close_blocks(); out.append("<ul>"); in_ul = True
            out.append(f"<li>{inline(s[2:])}</li>")
        else:
            close_blocks(); out.append(f"<p>{inline(s)}</p>")
    close_blocks()
    return "\n".join(out)


def svg_chart(series, markers, cur, width=760, height=300):
    """series: [(date, close)] sorted; markers: [(date, close, stance, label)]."""
    pl, pr, pt, pb = 64, 16, 14, 30
    x0, x1 = pl, width - pr
    y0, y1 = height - pb, pt
    d_min = datetime.strptime(series[0][0], "%Y-%m-%d")
    d_max = datetime.strptime(series[-1][0], "%Y-%m-%d")
    span = max((d_max - d_min).days, 1)
    vals = [v for _, v in series]
    v_min, v_max = min(vals), max(vals)
    pad = (v_max - v_min) * 0.06 or v_max * 0.06 or 1
    v_min, v_max = v_min - pad, v_max + pad

    def X(date):
        d = datetime.strptime(date, "%Y-%m-%d")
        return x0 + (d - d_min).days / span * (x1 - x0)

    def Y(v):
        return y0 + (v - v_min) / (v_max - v_min) * (y1 - y0)

    grid = []
    for i in range(5):
        v = v_min + (v_max - v_min) * i / 4
        y = Y(v)
        fmt = f"{v:,.2f}" if v_max < 100 else f"{v:,.0f}"
        grid.append(
            f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{x0 - 8}" y="{y + 4:.1f}" class="lab" text-anchor="end">{cur}{fmt}</text>'
        )
    mid = series[len(series) // 2][0]
    for date, anchor in ((series[0][0], "start"), (mid, "middle"), (series[-1][0], "end")):
        grid.append(f'<text x="{X(date):.1f}" y="{height - 8}" class="lab" text-anchor="{anchor}">{date}</text>')

    pts = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in series)
    dots = []
    for date, close, stance, label in markers:
        dots.append(
            f'<circle cx="{X(date):.1f}" cy="{Y(close):.1f}" r="4.5" fill="{STANCE_COLOR[stance]}" '
            f'stroke="var(--card)" stroke-width="1.5"><title>{html.escape(label)}</title></circle>'
        )
    return f"""<svg viewBox="0 0 {width} {height}" role="img" aria-label="價格走勢與提及標記">
  <style>.grid{{stroke:var(--line);stroke-width:1}}.lab{{fill:var(--muted);font-size:11px;font-family:ui-monospace,Menlo,monospace}}</style>
  {''.join(grid)}
  <polyline points="{pts}" fill="none" stroke="var(--accent)" stroke-width="2"/>
  {''.join(dots)}
</svg>"""


def render_page(cfg, ticker, con, calls):
    esc = html.escape
    display = account_display(cfg)
    accounts = get_accounts(cfg)
    industry = cfg.get("industries", {}).get(ticker, "（-）未分類")
    cur = cfg.get("currencies", {}).get(ticker, cfg.get("currencies", {}).get("_default", ""))
    cur = (cur + " ") if cur else ""

    rows = con.execute(
        """
        SELECT p.date, p.text, p.url, p.account, m.stance
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE m.ticker = ? ORDER BY p.date, p.ts
        """,
        (ticker,),
    ).fetchall()
    series = [
        (r["date"], r["close"])
        for r in con.execute("SELECT date, close FROM prices WHERE ticker=? ORDER BY date", (ticker,))
    ]

    by_account, stance_counts = {}, {}
    for r in rows:
        by_account[r["account"]] = by_account.get(r["account"], 0) + 1
        stance_counts[r["stance"]] = stance_counts.get(r["stance"], 0) + 1

    first, last = rows[0]["date"], rows[-1]["date"]
    fc, _ = close_on_or_before(con, ticker, first)
    lc, _ = close_on_or_before(con, ticker, last)
    chg = f"{(lc / fc - 1) * 100:+.1f}%" if fc and lc else "—"

    chart = ""
    if len(series) >= 2:
        markers = []
        for r in rows:
            px, _ = close_on_or_before(con, ticker, r["date"])
            if px is not None:
                who = display.get(r["account"], r["account"])
                markers.append((r["date"], px, r["stance"],
                                f"{r['date']} {who} {STANCE_ZH[r['stance']]}"))
        legend = " ".join(
            f'<span class="chip"><i style="background:{STANCE_COLOR[k]}"></i>{v}</span>'
            for k, v in STANCE_ZH.items()
        )
        chart = f'<div class="summary">{svg_chart(series, markers, cur)}<div class="note">{legend}　圓點＝提及日（顏色＝表態），滑過可看明細。</div></div>'

    ticker_calls = [c for c in calls if c["ticker"] == ticker]
    bt = ""
    if ticker_calls:
        lines = []
        for c in ticker_calls:
            rs = "・".join(
                f"{h}日 {c['returns'][h]:+.1f}%" if c["returns"].get(h) is not None else f"{h}日 —"
                for h in HORIZONS
            )
            lines.append(
                f'<div class="consensus-row"><span class="mono">{esc(c["date"])}</span>'
                f'<span>{esc(display.get(c["account"], c["account"]))}</span>'
                f'<span class="{ "up" if c["stance"] == "bull" else "down" }">{STANCE_ZH[c["stance"]]}</span>'
                f'<span class="chips mono">{rs}</span></div>'
            )
        bt = f"""
  <section>
    <h2>明確表態回測</h2>
    <p class="note">報酬以博主方向計（看空時下跌為正）；基準＝表態日（或其前最近交易日）收盤；未到期樣本顯示「—」。</p>
    <div class="summary">{''.join(lines)}</div>
  </section>"""

    analysis_path = ROOT / "data" / "analysis" / f"{ticker}-zh.md"
    if analysis_path.exists():
        analysis = f'<div class="summary analysis">{md_to_html(analysis_path.read_text(encoding="utf-8"))}</div>'
    else:
        analysis = (f'<p class="note">尚未撰寫。請 Claude 執行 `python3 scripts/query.py {esc(ticker)}` '
                    f'閱讀全紀錄後，把分析存至 `data/analysis/{esc(ticker)}-zh.md` 並重跑 detail.py。</p>')

    timeline = []
    for r in rows:
        stance_cls = {"bull": "up", "bear": "down"}.get(r["stance"], "flat")
        link = f' ・ <a class="tk" href="{esc(r["url"])}">原帖</a>' if r["url"] else ""
        timeline.append(f"""
      <div class="post">
        <div class="post-head mono">{esc(r["date"])} ・ {esc(display.get(r["account"], r["account"]))} ・
          <span class="{stance_cls}">{STANCE_ZH[r["stance"]]}</span>{link}</div>
        <blockquote>{esc(r["text"].strip())}</blockquote>
      </div>""")

    who = "・".join(f"{display.get(a, a)} {n}次" for a, n in sorted(by_account.items()))
    dist = "・".join(f"{STANCE_ZH[k]} {v}" for k, v in sorted(stance_counts.items()))

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(ticker)} 觀點追蹤</title>
<style>
  :root {{
    --bg:#faf8f4; --card:#ffffff; --ink:#26241f; --muted:#8a8578;
    --line:#e8e3d8; --accent:#b08d57; --up:#1a7f4b; --down:#c04545;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif; line-height:1.7; }}
  .wrap {{ max-width:820px; margin:0 auto; padding:32px 20px 64px; }}
  .mono {{ font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }}
  header h1 {{ font-size:28px; margin:0; font-family:ui-monospace,Menlo,monospace; }}
  header .ind {{ color:var(--muted); }}
  .stats {{ color:var(--muted); font-size:14px; margin:8px 0 0; }}
  .bigchg {{ font-size:18px; font-weight:700; }}
  section {{ margin-top:34px; }}
  h2 {{ font-size:17px; border-left:4px solid var(--accent); padding-left:10px; margin:0 0 10px; }}
  .summary {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }}
  .summary svg {{ width:100%; height:auto; display:block; }}
  .note {{ color:var(--muted); font-size:13px; margin:8px 0 0; }}
  .chip i {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px; }}
  .chip {{ margin-right:10px; font-size:12px; }}
  .consensus-row {{ display:flex; flex-wrap:wrap; gap:12px; padding:7px 0; border-bottom:1px solid var(--line); font-size:14px; }}
  .consensus-row:last-child {{ border-bottom:none; }}
  .chips {{ color:var(--muted); }}
  .up {{ color:var(--up); }} .down {{ color:var(--down); }} .flat {{ color:var(--muted); }}
  a.tk {{ color:inherit; border-bottom:1px dashed var(--muted); text-decoration:none; }}
  .post {{ border-bottom:1px solid var(--line); padding:12px 0; }}
  .post:last-child {{ border-bottom:none; }}
  .post-head {{ font-size:13px; color:var(--muted); }}
  blockquote {{ margin:6px 0 0; padding:2px 0 2px 14px; border-left:3px solid var(--line); }}
  .analysis h2 {{ border:none; padding:0; font-size:18px; }}
  .analysis h3 {{ font-size:15px; color:var(--accent); }}
  .analysis hr {{ border:none; border-top:1px solid var(--line); }}
  footer {{ margin-top:44px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:14px; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#191813; --card:#211f19; --ink:#e9e5da; --muted:#98917f;
             --line:#37342b; --up:#4dbd85; --down:#e07070; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{esc(ticker)} <span class="ind">{esc(industry)}</span></h1>
    <p class="stats">首提 {esc(first)}（{esc(cur)}{fc:,.2f}）→ 最近提及 {esc(last)}（{esc(cur)}{lc:,.2f}）
      <span class="bigchg {'up' if lc >= fc else 'down'}">{chg}</span><br>
      共 {len(rows)} 次提及：{esc(who)}<br>表態分佈：{esc(dist)}</p>
  </header>

  <section>
    <h2>價格走勢與提及點</h2>
    {chart or '<p class="note">價格資料不足，無法繪圖。</p>'}
  </section>
{bt}
  <section>
    <h2>觀點分析</h2>
    {analysis}
  </section>

  <section>
    <h2>提及時間軸（{len(rows)} 則）</h2>
    <div class="summary">{''.join(timeline)}</div>
  </section>

  <footer>
    本頁由自動化工具彙整公開貼文而成，不構成投資建議；內容可能有誤，請以原帖為準並自行核實（DYOR）。
  </footer>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "reports"), help="輸出目錄（頁面放在其下 tickers/）")
    ap.add_argument("--tickers", nargs="*", help="只產生指定代碼（預設全部）")
    args = ap.parse_args()

    cfg = load_config()
    con = connect()
    calls = compute_calls(con)
    tickers = args.tickers or [
        r["ticker"] for r in con.execute("SELECT DISTINCT ticker FROM mentions ORDER BY ticker")
    ]
    out_dir = Path(args.out) / "tickers"
    out_dir.mkdir(parents=True, exist_ok=True)
    for t in tickers:
        t = t.upper()
        page = render_page(cfg, t, con, calls)
        (out_dir / f"{t}-zh.html").write_text(page, encoding="utf-8")
    print(f"已產生 {len(tickers)} 頁 → {out_dir}")


if __name__ == "__main__":
    main()
