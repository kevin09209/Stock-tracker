"""Extract $TICKER mentions from stored posts and classify the stance of each.

Stance per (post, ticker):
  bull       明確看多（long/buy/accumulate/看多…）
  bear       明確看空（short/sell/trim/看空…）
  neutral    有評論但方向不明確
  background 僅背景提及（清單、轉述、對照組）

Heuristics only — for higher-quality classification let Claude re-label via
`python3 scripts/query.py TICKER` and edit the mentions table.

Usage: python3 scripts/ingest.py [--rebuild]
"""
import argparse
import re

from db import connect, load_config

CASHTAG = re.compile(r"\$([A-Za-z]{1,5})(?:\.[A-Za-z]{1,3})?\b")

BULL_WORDS = [
    "long", "buy", "buying", "bought", "accumulate", "adding", "added", "bullish",
    "upside", "undervalued", "top pick", "conviction", "moon", "breakout",
    "看多", "做多", "加倉", "建倉", "買入", "低估",
]
BEAR_WORDS = [
    "short", "shorting", "sell", "selling", "sold", "trim", "trimmed", "bearish",
    "overvalued", "puts", "downside", "avoid", "bubble",
    "看空", "做空", "減倉", "賣出", "高估", "泡沫",
]
# words that signal actual commentary (vs a bare list of tickers)
OPINION_WORDS = [
    "think", "believe", "expect", "thesis", "view", "estimate", "guidance",
    "should", "will", "risk", "catalyst", "覺得", "認為", "預期", "論點",
]


def sentences(text):
    return re.split(r"(?<=[.!?。！？])\s+|\n+", text)


def has_word(words, text):
    """Word-boundary match for ASCII terms, substring for CJK terms."""
    for w in words:
        if w.isascii():
            if re.search(rf"\b{re.escape(w)}\b", text):
                return True
        elif w in text:
            return True
    return False


def classify(sentence):
    s = sentence.lower()
    # time expressions, not trading directions
    s = re.sub(r"\b(short|long)[- ](term|run|dated)\b", "", s)
    bull = has_word(BULL_WORDS, s)
    bear = has_word(BEAR_WORDS, s)
    if bull and not bear:
        return "bull"
    if bear and not bull:
        return "bear"
    if bull and bear:
        return "neutral"
    if has_word(OPINION_WORDS, s):
        return "neutral"
    return "background"


RANK = {"background": 0, "neutral": 1, "bear": 2, "bull": 2}


def extract(text, blocklist):
    """-> {ticker: stance}, strongest stance wins across sentences.

    A stance sentence often doesn't repeat the cashtag ("$SIVE ... . I am long."),
    so when sentence-level matching only yields background/neutral and the post
    discusses few tickers, fall back to the whole-post stance.
    """
    out = {}
    for sent in sentences(text):
        tickers = {m.group(1).upper() for m in CASHTAG.finditer(sent)}
        tickers -= blocklist
        if not tickers:
            continue
        stance = classify(sent)
        for t in tickers:
            if t not in out or RANK[stance] > RANK[out[t]]:
                out[t] = stance

    if out and len(out) <= 3:
        post_stance = classify(text)
        for t, stance in out.items():
            if RANK[post_stance] > RANK[stance]:
                out[t] = post_stance
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true", help="清除並重建所有 mentions")
    args = ap.parse_args()

    cfg = load_config()
    blocklist = set(cfg.get("ticker_blocklist", []))
    con = connect()

    if args.rebuild:
        con.execute("DELETE FROM mentions")
        rows = con.execute("SELECT id, text FROM posts").fetchall()
    else:
        rows = con.execute(
            "SELECT id, text FROM posts WHERE id NOT IN (SELECT DISTINCT post_id FROM mentions)"
        ).fetchall()

    n = 0
    for row in rows:
        for ticker, stance in extract(row["text"], blocklist).items():
            con.execute(
                "INSERT OR REPLACE INTO mentions(post_id, ticker, stance) VALUES(?,?,?)",
                (row["id"], ticker, stance),
            )
            n += 1
    con.commit()
    print(f"處理 {len(rows)} 則貼文，寫入 {n} 筆提及")


if __name__ == "__main__":
    main()
