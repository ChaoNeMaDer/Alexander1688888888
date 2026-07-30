"""
資料擷取模組
- 從 TWSE/TPEx API 取得股票清單與當日行情
- 使用 yfinance 下載歷史數據
"""
import time
import warnings
import requests
import urllib3
import pandas as pd
import yfinance as yf
from tqdm import tqdm
import config

# 關閉 SSL 警告（部分環境 SSL 憑證問題）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def get_stock_list():
    """從證交所/櫃買中心 API 取得所有個股（排除 ETF），篩選成交量與股價範圍"""
    stocks = []

    # ── 上市股票 (TWSE) ──
    print("📡 取得上市股票清單...")
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        resp = requests.get(url, timeout=30, verify=False)
        resp.raise_for_status()
        for item in resp.json():
            code = item.get("Code", "").strip()
            name = item.get("Name", "").strip()
            vol_str = item.get("TradeVolume", "0").replace(",", "")
            close_str = item.get("ClosingPrice", "0").replace(",", "")
            open_str = item.get("OpeningPrice", "0").replace(",", "")
            high_str = item.get("HighestPrice", "0").replace(",", "")
            low_str = item.get("LowestPrice", "0").replace(",", "")

            # 只取 4 碼純數字（個股），排除 ETF (00xx)、權證等
            if not (len(code) == 4 and code.isdigit()):
                continue
            if code.startswith("00"):
                continue

            try:
                volume = int(float(vol_str))
                close_p = _safe_float(close_str)
                open_p = _safe_float(open_str)
            except (ValueError, TypeError):
                continue

            if volume < config.MIN_VOLUME_SHARES:
                continue
            if close_p <= 0:
                continue
            if close_p > config.MAX_PRICE:
                continue

            stocks.append({
                "code": code,
                "name": name,
                "market": "TWSE",
                "ticker": f"{code}.TW",
                "volume": volume,
                "close": close_p,
                "open": open_p,
            })
    except Exception as e:
        print(f"  ⚠️ TWSE API 錯誤: {e}")

    twse_count = len(stocks)
    print(f"  ✅ 上市股票: {twse_count} 檔通過篩選")

    # ── 上櫃股票 (TPEx) ──
    print("📡 取得上櫃股票清單...")
    tpex_count = 0
    try:
        url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
        resp = requests.get(url, timeout=30, verify=False)
        resp.raise_for_status()
        for item in resp.json():
            code = item.get("SecuritiesCompanyCode", "").strip()
            name = item.get("CompanyName", "").strip()
            vol_str = item.get("TradingShares", "0").replace(",", "")
            close_str = item.get("Close", "0").replace(",", "")
            open_str = item.get("Open", "0").replace(",", "")

            if not (len(code) == 4 and code.isdigit()):
                continue
            if code.startswith("00"):
                continue

            try:
                volume = int(float(vol_str))
                close_p = _safe_float(close_str)
                open_p = _safe_float(open_str)
            except (ValueError, TypeError):
                continue

            if volume < config.MIN_VOLUME_SHARES:
                continue
            if close_p <= 0:
                continue
            if close_p > config.MAX_PRICE:
                continue

            tpex_count += 1
            stocks.append({
                "code": code,
                "name": name,
                "market": "TPEx",
                "ticker": f"{code}.TWO",
                "volume": volume,
                "close": close_p,
                "open": open_p,
            })
    except Exception as e:
        print(f"  ⚠️ TPEx API 錯誤: {e}")

    print(f"  ✅ 上櫃股票: {tpex_count} 檔通過篩選")
    print(f"📊 合計: {len(stocks)} 檔股票待掃描\n")
    return stocks


def download_historical(tickers, period=None):
    """
    分批下載歷史日K數據。
    回傳 dict: { ticker: DataFrame(Open,High,Low,Close,Volume) }
    """
    if period is None:
        period = config.DOWNLOAD_PERIOD

    batch_size = config.DOWNLOAD_BATCH_SIZE
    all_data = {}
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]

    print(f"📥 下載歷史數據... ({len(tickers)} 檔, {len(batches)} 批)")

    for batch_idx, batch in enumerate(tqdm(batches, desc="下載進度")):
        try:
            data = yf.download(
                tickers=batch,
                period=period,
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
            )

            if data is None or data.empty:
                continue

            if len(batch) == 1:
                ticker = batch[0]
                try:
                    df = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
                    if len(df) > 0:
                        all_data[ticker] = df
                except KeyError:
                    pass
            else:
                for ticker in batch:
                    try:
                        df = data[ticker][["Open", "High", "Low", "Close", "Volume"]].dropna()
                        if len(df) > 0:
                            all_data[ticker] = df
                    except (KeyError, TypeError):
                        continue

        except Exception as e:
            tqdm.write(f"  ⚠️ 批次 {batch_idx + 1} 錯誤: {e}")

        if batch_idx < len(batches) - 1:
            time.sleep(config.DOWNLOAD_DELAY)

    print(f"✅ 成功下載 {len(all_data)} 檔股票數據\n")
    return all_data


def resample_to_weekly(daily_df):
    """將日K數據重新取樣為週K"""
    weekly = daily_df.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()
    return weekly


def _safe_float(s):
    """安全轉換字串為 float"""
    if not s or s in ("--", "-", "", "X"):
        return 0.0
    try:
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return 0.0
