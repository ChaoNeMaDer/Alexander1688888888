"""
箱波均戰法 — 自動排程用進入點
由 Windows 工作排程器呼叫，靜默執行並產生 Excel + HTML 報表
不開啟瀏覽器、不等待使用者輸入
"""
import os
import sys
import json
import glob
import logging
from datetime import datetime

# 設定工作目錄為腳本所在位置
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# 設定 log
log_path = os.path.join(script_dir, "auto_run.log")
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)

def cleanup_old_reports(output_dir, keep_date_str):
    """
    只保留今天的報表，刪除其他日期的舊報表。
    Web 介面（pages/2_箱波均戰法選股.py）只讀取最新一份 JSON，
    不需要保留歷史報表；每天都 commit 進 repo 會讓 repo 體積無限增長。
    """
    for pattern in ("report_*.html", "report_*.xlsx", "results_*.json"):
        for path in glob.glob(os.path.join(output_dir, pattern)):
            if keep_date_str not in os.path.basename(path):
                try:
                    os.remove(path)
                    logging.info(f"已刪除舊報表: {path}")
                except OSError as e:
                    logging.warning(f"刪除舊報表失敗: {path} ({e})")


def main():
    logging.info("=" * 50)
    logging.info("自動選股排程開始執行")

    try:
        import config
        import data_fetcher
        import boxwave_engine
        import report_generator
        import excel_generator

        # ── Step 1: 取得股票清單 ──
        stocks = data_fetcher.get_stock_list()
        if not stocks:
            logging.error("無法取得股票清單")
            return

        stock_info = {s["ticker"]: s for s in stocks}
        tickers = [s["ticker"] for s in stocks]
        total_scanned = len(tickers)
        logging.info(f"取得 {total_scanned} 檔股票")

        # ── Step 2: 下載歷史日K數據 ──
        daily_data = data_fetcher.download_historical(tickers)
        if not daily_data:
            logging.error("無法下載歷史數據")
            return

        logging.info(f"成功下載 {len(daily_data)} 檔歷史數據")

        # ── Step 3: 掃描 ──
        results = []
        skipped = 0

        for ticker, daily_df in daily_data.items():
            try:
                weekly_df = data_fetcher.resample_to_weekly(daily_df)

                w_result = boxwave_engine.calc_signal_and_trend(
                    weekly_df,
                    config.WEEKLY_MA,
                    config.PIVOT_LEN_WEEKLY,
                    config.GAP_PCT_WEEKLY,
                    config.CONVERGE_PCT_WEEKLY,
                    config.BODY_MIN_PCT,
                )

                if w_result is None or w_result["last_sig"] != 1:
                    continue

                d_result = boxwave_engine.calc_signal_and_trend(
                    daily_df,
                    config.DAILY_MA,
                    config.PIVOT_LEN_DAILY,
                    config.GAP_PCT_DAILY,
                    config.CONVERGE_PCT_DAILY,
                    config.BODY_MIN_PCT,
                )

                if d_result is None or not d_result["is_new_buy_today"]:
                    continue

                info = stock_info.get(ticker, {})
                last_bar = daily_df.iloc[-1]
                close_price = float(last_bar["Close"])
                volume_shares = int(last_bar["Volume"])

                if len(daily_df) >= 2:
                    prev_close = float(daily_df.iloc[-2]["Close"])
                    change_pct = (close_price - prev_close) / prev_close * 100
                else:
                    change_pct = 0

                trend_labels = config.TREND_LABELS

                results.append({
                    "code": info.get("code", ticker.split(".")[0]),
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
                })

            except Exception as e:
                skipped += 1
                logging.warning(f"{ticker} 掃描時發生錯誤，已略過: {e}")
                continue

        logging.info(f"掃描完成: 符合 {len(results)} 檔, 跳過 {skipped} 檔")

        # ── Step 4: 排序 ──
        if results:
            results.sort(key=lambda x: x["change_pct"], reverse=True)

        # ── Step 5: 產生報表 ──
        output_dir = config.OUTPUT_DIR
        os.makedirs(output_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")

        # Excel 報表
        excel_path = os.path.join(output_dir, f"report_{date_str}.xlsx")
        abs_excel = excel_generator.generate_excel(results, total_scanned, excel_path)
        logging.info(f"Excel 報表已儲存: {abs_excel}")

        # HTML 報表
        report_path = os.path.join(output_dir, f"report_{date_str}.html")
        abs_html = report_generator.generate_report(results, total_scanned, report_path)
        logging.info(f"HTML 報表已儲存: {abs_html}")

        # ── Step 6: 輸出結構化資料供 Web 介面讀取 ──
        json_path = os.path.join(output_dir, f"results_{date_str}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {"date": date_str, "total_scanned": total_scanned, "results": results},
                f,
                ensure_ascii=False,
            )
        logging.info(f"JSON 結果已儲存: {json_path}")

        # ── Step 7: 清除舊報表，避免每天累積導致 repo 體積無限增長 ──
        cleanup_old_reports(output_dir, date_str)

        logging.info("自動選股排程執行完成 ✅")

    except Exception as e:
        logging.exception(f"執行失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
