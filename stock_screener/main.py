"""
箱波均戰法 — 台股全市場掃描選股程式
篩選條件：週K 已在買進狀態 + 日K 當日出現新買進訊號
"""
import os
import sys
import webbrowser
from collections import Counter
from datetime import datetime

from tqdm import tqdm

import config
import data_fetcher
import boxwave_engine
import report_generator
import excel_generator


def main():
    print("=" * 60)
    print("📊 箱波均戰法 — 台股全市場掃描")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 篩選條件：週K已買進 + 日K當日新買進")
    print(f"📋 最低成交量：{config.MIN_VOLUME_LOTS} 張")
    print("=" * 60 + "\n")

    # ── Step 1: 取得股票清單 ──
    stocks = data_fetcher.get_stock_list()
    if not stocks:
        print("❌ 無法取得股票清單，請檢查網路連線")
        return

    # 建立快速查詢 dict
    stock_info = {s["ticker"]: s for s in stocks}
    tickers = [s["ticker"] for s in stocks]
    total_scanned = len(tickers)

    # ── Step 2: 下載歷史日K數據 ──
    daily_data = data_fetcher.download_historical(tickers)
    if not daily_data:
        print("❌ 無法下載歷史數據")
        return

    # ── Step 2.5: 取得三大法人買賣超（全市場一次性資料，用股票代號查表）──
    inst_flows, inst_date = data_fetcher.fetch_institutional_flows()
    inst_history, _ = data_fetcher.fetch_institutional_flows_history(config.INST_STREAK_TRADING_DAYS)

    # 三大法人資料（T86）的日期是靠 TWSE 是否已公布來判斷，天生就會正確跳過假日；
    # 拿它來檢查 yfinance 股價資料是否落後，比自己猜測日曆假日可靠。
    price_dates = Counter(df.index[-1].strftime("%Y%m%d") for df in daily_data.values())
    latest_price_date = price_dates.most_common(1)[0][0] if price_dates else None
    if inst_date and latest_price_date and latest_price_date < inst_date:
        print(f"⚠️ 股價資料最新日期（{latest_price_date}）早於三大法人資料日期（{inst_date}），"
              f"yfinance 資料可能延遲更新，本次掃描的漲跌幅／買進訊號可能不是最新交易日的資料")

    # ── Step 3: 掃描每檔股票 ──
    results = []
    skipped = 0

    print(f"🔍 開始掃描 {len(daily_data)} 檔股票...\n")

    for ticker, daily_df in tqdm(daily_data.items(), desc="掃描進度"):
        try:
            # 週K：將日K重新取樣
            weekly_df = data_fetcher.resample_to_weekly(daily_df)

            # 週K 引擎
            w_result = boxwave_engine.calc_signal_and_trend(
                weekly_df,
                config.WEEKLY_MA,
                config.PIVOT_LEN_WEEKLY,
                config.GAP_PCT_WEEKLY,
                config.CONVERGE_PCT_WEEKLY,
                config.BODY_MIN_PCT,
            )

            if w_result is None or w_result["last_sig"] != 1:
                # 週K 不在買進狀態 → 跳過
                continue

            if w_result["trend_code"] not in (1, 2):
                # 狀態機仍停在買進（還沒觸發明確賣出訊號），但週K均線排列
                # 已經轉弱成糾結/中性/空頭 → 視為趨勢已經鬆動，不放行
                continue

            # 日K 引擎
            d_result = boxwave_engine.calc_signal_and_trend(
                daily_df,
                config.DAILY_MA,
                config.PIVOT_LEN_DAILY,
                config.GAP_PCT_DAILY,
                config.CONVERGE_PCT_DAILY,
                config.BODY_MIN_PCT,
            )

            if d_result is None or not d_result["is_new_buy_today"]:
                # 日K 今天沒有新買進訊號 → 跳過
                continue

            # ── 通過雙重篩選! ──
            info = stock_info.get(ticker, {})

            # 使用 yfinance 歷史數據的最後一根 K 棒（確保是最新收盤價）
            last_bar = daily_df.iloc[-1]
            close_price = float(last_bar["Close"])
            open_price = float(last_bar["Open"])
            volume_shares = int(last_bar["Volume"])

            # 漲跌幅 = (今日收盤 - 昨日收盤) / 昨日收盤
            if len(daily_df) >= 2:
                prev_close = float(daily_df.iloc[-2]["Close"])
                change_pct = (close_price - prev_close) / prev_close * 100
            else:
                change_pct = 0

            trend_labels = config.TREND_LABELS
            code = info.get("code", ticker.split(".")[0])

            # 三大法人買賣超（股數 → 張數）；T86 查不到就是 None，代表當天沒有這檔的法人資料
            flow = inst_flows.get(code)
            foreign_lots = flow["foreign_net"] // 1000 if flow else None
            trust_lots = flow["trust_net"] // 1000 if flow else None
            dealer_lots = flow["dealer_net"] // 1000 if flow else None
            total_lots = flow["total_net"] // 1000 if flow else None

            # 連續買超/賣超天數（籌碼面確認標籤，不影響技術面篩選結果）
            hist = inst_history.get(code, [])
            foreign_streak = data_fetcher.compute_streak([h["foreign_net"] for h in hist])
            trust_streak = data_fetcher.compute_streak([h["trust_net"] for h in hist])
            dealer_streak = data_fetcher.compute_streak([h["dealer_net"] for h in hist])
            total_streak = data_fetcher.compute_streak([h["total_net"] for h in hist])

            results.append({
                "code": code,
                "name": info.get("name", ""),
                "market": info.get("market", ""),
                "close": close_price,
                "change_pct": change_pct,
                "volume_lots": volume_shares // 1000,
                "daily_buy_reason": d_result["buy_reason"],
                "daily_trend_code": d_result["trend_code"],
                "daily_trend_text": trend_labels.get(d_result["trend_code"], ""),
                "weekly_reason": w_result["reason"],
                "weekly_trend_code": w_result["trend_code"],
                "weekly_trend_text": trend_labels.get(w_result["trend_code"], ""),
                "inst_date": inst_date,
                "foreign_lots": foreign_lots,
                "trust_lots": trust_lots,
                "dealer_lots": dealer_lots,
                "total_lots": total_lots,
                "foreign_streak": foreign_streak,
                "trust_streak": trust_streak,
                "dealer_streak": dealer_streak,
                "total_streak": total_streak,
            })

        except Exception as e:
            skipped += 1
            tqdm.write(f"  ⚠️ {ticker} 掃描時發生錯誤，已略過: {e}")
            continue

    # ── Step 4: 產生報表 ──
    print(f"\n{'=' * 60}")
    print(f"✅ 掃描完成！")
    print(f"   掃描: {total_scanned} 檔  |  符合條件: {len(results)} 檔  |  跳過: {skipped} 檔")
    print(f"{'=' * 60}\n")

    if results:
        # 按漲跌幅排序
        results.sort(key=lambda x: x["change_pct"], reverse=True)

        # Console 摘要
        print("📋 符合條件的股票：")
        print(f"{'代碼':>6}  {'名稱':<8}  {'收盤':>8}  {'漲跌幅':>8}  {'日K原因':<10}  {'週K原因':<10}")
        print("-" * 70)
        for r in results:
            chg = f"+{r['change_pct']:.2f}%" if r["change_pct"] >= 0 else f"{r['change_pct']:.2f}%"
            print(f"{r['code']:>6}  {r['name']:<8}  {r['close']:>8.2f}  {chg:>8}  "
                  f"{r['daily_buy_reason']:<10}  {r['weekly_reason']:<10}")
        print()

    # 產生報表
    output_dir = config.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")

    # HTML 報表
    report_path = os.path.join(output_dir, f"report_{date_str}.html")
    abs_path = report_generator.generate_report(results, total_scanned, report_path)
    print(f"📄 HTML 報表已儲存: {abs_path}")

    # Excel 報表
    excel_path = os.path.join(output_dir, f"report_{date_str}.xlsx")
    abs_excel = excel_generator.generate_excel(results, total_scanned, excel_path)
    print(f"📊 Excel 報表已儲存: {abs_excel}")

    # 開啟瀏覽器
    webbrowser.open(f"file:///{abs_path}")
    print("🌐 已開啟瀏覽器顯示報表")


if __name__ == "__main__":
    main()
