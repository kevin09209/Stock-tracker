---
name: serenity-watch
description: 追蹤一位或多位 X 股票分析帳號（預設 Serenity @aleabitoreddit）的個股提及，產生繁體中文每日 HTML 日報（含多博主共識比對）與個股觀點深度分析。當使用者要求「今天的日報」「更新追蹤」「怎麼看某一檔股票」「加追蹤某帳號」時使用。
---

# Serenity Watch — X 股票大神追蹤器

追蹤一位或多位 X 上的股票分析帳號，把他們提過的每一檔標的建檔：提及次數、
看多／看空表態、首次提及日期與價格、最新價格與漲幅，並產出繁體中文 HTML 日報；
追蹤多帳號時自動加入「博主共識」區塊（近7日 ≥2 位博主提及的標的，逐檔比對淨表態）。

所有指令都在本 skill 目錄下執行（`cd` 到本目錄或用絕對路徑）。資料存在 `data/tracker.db`（SQLite）。

## 每日更新流程（使用者說「更新」「產生今天的日報」時）

```bash
python3 scripts/fetch.py --x-api        # 需要環境變數 TWITTER_BEARER_TOKEN
python3 scripts/ingest.py               # 擷取 $代碼 提及並粗分類表態
python3 scripts/prices.py               # 從 Stooq 抓每檔標的的日收盤價
python3 scripts/report.py               # 產生日報（含博主共識、戰績記分卡）
python3 scripts/detail.py               # 產生個股詳情頁 reports/tickers/{代碼}-zh.html
```

沒有 X API 金鑰時，用 JSON 匯入貼文（格式見 `data/sample_posts.json`）：

```bash
python3 scripts/fetch.py --import <貼文.json>
python3 scripts/prices.py --import <價格.json>   # 離線價格，格式見 data/sample_prices.json
```

產出檔案路徑會印在 stdout，把它交給使用者（或直接開啟預覽）。

## 個股深度分析（使用者問「他怎麼看 XXXX」時）

1. 先跑 `python3 scripts/query.py TICKER` 取得該標的的完整提及紀錄（Markdown：
   日期、博主、表態、原文）。
2. 讀取輸出後，**由你（Claude）撰寫**繁體中文分析，結構如下：
   - 標題：`TICKER — {博主} 觀點分析`，附追蹤期與明確表態次數
   - **叙事弧線**：一段連貫敘事，講博主對這檔股票的論點如何隨時間演進，
     引用關鍵日期與原文短句（保留英文原句），並對照當時股價
   - **關鍵觀點（N 條）**：挑 3–5 則轉折點貼文，每則格式
     `[日期] — 主題：一句話摘要`
3. 結尾必附免責聲明：內容彙整自公開貼文，不構成投資建議，請以原帖為準（DYOR）。
4. 把完成的分析存到 `data/analysis/{TICKER}-zh.md`（範例見 `data/analysis/SIVE-zh.md`），
   再跑 `python3 scripts/detail.py --tickers TICKER`——分析會自動嵌入該股詳情頁，
   與走勢圖、逐筆回測、提及時間軸放在同一頁。回覆使用者時附上詳情頁路徑。

## 博主戰績（使用者問「這位博主準嗎」「誰比較準」時）

跑 `python3 scripts/backtest.py`：對每次明確看多／看空表態計算 7/30/90 日後
報酬（以博主方向計，看空時下跌為正），輸出各博主命中率記分卡＋逐筆明細。
日報末段也有同一份記分卡。轉述時務必附口徑說明與「過去戰績不代表未來」。

## 表態分類口徑

`ingest.py` 用關鍵字粗分：bull（看多）/ bear（看空）/ neutral（中性）/ background（僅背景提及）。
若使用者要求更精準的表態統計，逐則讀 `query.py` 的原文重新判斷，並更新
`mentions` 表（`UPDATE mentions SET stance=? WHERE post_id=? AND ticker=?`）。

## 設定

`config.json`：追蹤帳號清單（`accounts` 陣列）、時區、行業對照（`industries`）、
非美股價格代號（`price_symbols`，如 SIVE → sive.se）、幣別（`currencies`）、
誤判黑名單（`ticker_blocklist`）。使用者說「加追蹤某帳號」時，在 `accounts`
陣列加一個 `{"handle", "display", "description"}` 物件後重新 fetch 即可；
資料庫按帳號分開記錄，`query.py` 輸出會標明每則貼文出自哪位博主。

## 原則

- 一律使用繁體中文輸出報告與分析（程式碼與原文引用除外）。
- 不給任何買賣建議；只彙整、統計、轉述博主的公開觀點。
- 漲幅口徑固定：首次提及日收盤 → 最近提及日收盤，資料缺漏顯示「—」。
