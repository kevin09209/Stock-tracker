# Stock Tracker — X 股票大神追蹤器

追蹤一位或多位 X（Twitter）上的股票分析帳號（預設示範：Serenity @aleabitoreddit，
AI／半導體供應鏈分析師），自動建檔他們提過的每一檔標的，並產生**繁體中文每日 HTML 日報**。

> 本工具與被追蹤帳號本人無任何關聯，亦不構成投資建議——僅為方便研究。

## 功能

- **貼文擷取**：X API v2（需金鑰）或 JSON 匯入，支援同時追蹤多個帳號
- **標的建檔**：自動擷取 `$代碼`，判斷每次提及的表態（看多／看空／中性／僅背景提及）
- **博主共識**（多帳號時）：近7日有 ≥2 位博主提及的標的，逐檔比對各博主淨表態
  （一致看多／一致看空／偏多／偏空／多空分歧）
- **博主戰績記分卡**：回測每次明確看多／看空表態的 7／30／90 日後實際報酬
  （以博主方向計），彙總各博主命中率與平均報酬，附在日報末段
- **個股詳情頁**：日報季度表的代碼可點入——價格走勢圖（SVG，提及日打點、
  顏色＝表態）、逐筆表態回測、觀點分析（叙事弧線＋關鍵觀點）、完整提及時間軸
- **價格對照**：Stooq 免費日線（美股與歐股皆可，代號可在設定覆寫）
- **每日日報**（`reports/*.html`，深淺色主題自適應）：
  - 今日 N 檔標的・M 次提及、市場淨看多／看空比例
  - 今天重點討論的標的卡片：當天／7日／28日提及次數、今日表態、首提日期、較上一交易日漲跌
  - 季度全標的表（可點欄位排序）：代碼、行業、首次提及（日期＋價）、最近提及（日期＋價）、漲幅、提及次數
- **個股觀點分析**：`query.py` 匯出某檔標的的完整提及紀錄，配合 Claude 撰寫
  「叙事弧線＋關鍵觀點」深度分析（見 `SKILL.md`）

## 快速開始（離線示範）

```bash
python3 scripts/fetch.py  --import data/sample_posts.json           # 博主 1
python3 scripts/fetch.py  --import data/sample_posts_account2.json  # 博主 2
python3 scripts/ingest.py
python3 scripts/prices.py --import data/sample_prices.json
python3 scripts/report.py            # → reports/multi-tracker-2026-07-02-zh.html
python3 scripts/detail.py            # → reports/tickers/{代碼}-zh.html（詳情頁）
python3 scripts/backtest.py          # 終端機直接看記分卡與逐筆回測明細
python3 scripts/query.py SIVE        # 個股提及全紀錄（餵給 Claude 做深度分析）
```

完整示範輸出（含詳情頁）收錄在 [`reports/demo/`](reports/demo/)。

純 Python 標準庫，無第三方依賴（Python 3.9+，需 `zoneinfo` 時區資料）。

## 實際追蹤

```bash
export TWITTER_BEARER_TOKEN=...      # X API v2 Bearer Token
python3 scripts/fetch.py --x-api     # 逐帳號增量抓取（自動從上次停的地方續抓）
python3 scripts/ingest.py
python3 scripts/prices.py
python3 scripts/report.py
python3 scripts/detail.py
```

每天排程跑一次即可（cron 或 Claude Code 的排程任務）。

追蹤帳號在 `config.json` 的 `accounts` 陣列設定，加一個物件就多追一個帳號：

```json
{"handle": "dylan522p", "display": "Dylan Patel", "description": "SemiAnalysis"}
```

X API 讀取額度按貼文數計費（Basic 方案月費約 US$200，額度以官方定價頁為準）；
追蹤 5–10 位日更博主的用量通常遠低於上限，fetch 為增量抓取不會重複耗費額度。

## 當作 Claude Skill 使用

本 repo 同時是一個 Claude Code skill（見 `SKILL.md`）。安裝：

```bash
cp -r . ~/.claude/skills/serenity-watch
```

之後在 Claude Code 裡直接說「產生今天的日報」或「他怎麼看 SIVE」即可。

## 設定（config.json）

| 欄位 | 說明 |
|---|---|
| `accounts` | 要追蹤的 X 帳號清單（`handle` 不含 @，`display` 為報告顯示名） |
| `industries` | 代碼 → 行業標籤（表格「行業」欄，未列＝（-）未分類） |
| `price_symbols` | 非美股的 Stooq 代號覆寫，如 `"SIVE": "sive.se"` |
| `currencies` | 非美元計價標的的幣別標示，如 `"SIVE": "SEK"` |
| `ticker_blocklist` | 避免把 `$CEO`、`$GDP` 之類誤認為代碼 |
| `report.quarterly_table_min_mentions_90d` | 季度表收錄門檻（近90日提及次數） |

## 免責聲明

所有內容彙整自公開貼文，可能有誤；表態分類為程式粗判，請以原帖為準並自行核實
（DYOR）。本工具不提供任何買賣建議。
