"""Fetch posts from the tracked X account into the local database.

Two sources:
  1. X API v2 (needs env TWITTER_BEARER_TOKEN):   python3 scripts/fetch.py --x-api
  2. JSON file import (offline / manual export):  python3 scripts/fetch.py --import data/sample_posts.json

JSON format: a list of {"id": str, "ts": ISO8601 str, "text": str, "url": str(optional)}
Dates are bucketed to the account timezone (config.timezone, default US/Eastern).
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from db import connect, load_config

X_API = "https://api.twitter.com/2"


def to_local_date(ts_iso, tz):
    dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d")


def upsert_posts(con, posts, tz):
    n = 0
    for p in posts:
        cur = con.execute(
            "INSERT OR IGNORE INTO posts(id, date, ts, text, url) VALUES(?,?,?,?,?)",
            (str(p["id"]), to_local_date(p["ts"], tz), p["ts"], p["text"], p.get("url", "")),
        )
        n += cur.rowcount
    con.commit()
    return n


def x_api_get(path, params, token):
    url = f"{X_API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_from_x(con, cfg, tz):
    token = os.environ.get("TWITTER_BEARER_TOKEN")
    if not token:
        sys.exit("TWITTER_BEARER_TOKEN 未設定；改用 --import 匯入 JSON，或設定 X API 金鑰")
    handle = cfg["account"]["handle"]
    user = x_api_get(f"/users/by/username/{handle}", {}, token)["data"]
    latest = con.execute("SELECT MAX(id) AS m FROM posts").fetchone()["m"]

    params = {
        "max_results": 100,
        "tweet.fields": "created_at",
        "exclude": "retweets,replies",
    }
    if latest:
        params["since_id"] = latest

    total, page = 0, None
    while True:
        if page:
            params["pagination_token"] = page
        data = x_api_get(f"/users/{user['id']}/tweets", params, token)
        posts = [
            {
                "id": t["id"],
                "ts": t["created_at"],
                "text": t["text"],
                "url": f"https://x.com/{handle}/status/{t['id']}",
            }
            for t in data.get("data", [])
        ]
        total += upsert_posts(con, posts, tz)
        page = data.get("meta", {}).get("next_token")
        if not page:
            break
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--x-api", action="store_true", help="從 X API v2 抓取")
    src.add_argument("--import", dest="import_file", help="匯入 JSON 貼文檔")
    args = ap.parse_args()

    cfg = load_config()
    tz = ZoneInfo(cfg.get("timezone", "America/New_York"))
    con = connect()

    if args.import_file:
        posts = json.loads(open(args.import_file, encoding="utf-8").read())
        n = upsert_posts(con, posts, tz)
    else:
        n = fetch_from_x(con, cfg, tz)
    print(f"新增 {n} 則貼文（資料庫共 {con.execute('SELECT COUNT(*) c FROM posts').fetchone()['c']} 則）")


if __name__ == "__main__":
    main()
