"""
資料擷取模組
- 從 TWSE API 取得上市股票清單、當日行情與三大法人買賣超
- 使用 yfinance 下載歷史數據
"""
import time
import warnings
from datetime import datetime, timedelta
import requests
import pandas as pd
import yfinance as yf
from tqdm import tqdm
import config

warnings.filterwarnings("ignore", category=FutureWarning)


def get_stock_list():
    """從證交所 API 取得上市個股（排除 ETF），篩選成交量與股價範圍。只掃上市，不含上櫃(TPEx)。"""
    stocks = []

    # ── 上市股票 (TWSE) ──
    print("📡 取得上市股票清單...")
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        resp = requests.get(url, timeout=30)
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
    print(f"📊 合計: {len(stocks)} 檔股票待掃描\n")
    return stocks


def fetch_institutional_flows(max_lookback_days=5):
    """
    抓 TWSE 三大法人買賣超日報（T86），全市場一天只需一次 API 呼叫。
    自動往前找最近一個有資料的交易日（今天若尚未收盤/未公布則往前找）。
    只涵蓋上市（TWSE）股票，回傳 (flows, date_str)：
        flows: { 股票代號: {foreign_net, trust_net, dealer_net, total_net} }（單位：股）
        date_str: 實際取得資料的日期 (YYYYMMDD)，找不到則為 None
    """
    base_date = datetime.now()
    for i in range(max_lookback_days):
        date_str = (base_date - timedelta(days=i)).strftime("%Y%m%d")
        try:
            resp = requests.get(
                f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALL",
                timeout=30
            )
            data = resp.json()
        except Exception as e:
            print(f"  ⚠️ {date_str} 三大法人資料取得失敗: {e}")
            continue

        if data.get("stat") != "OK" or not data.get("data"):
            continue

        flows = {}
        for row in data["data"]:
            rec = dict(zip(data["fields"], row))
            code = rec.get("證券代號", "").strip()

            def _n(key):
                return _safe_float(rec.get(key, "0"))

            flows[code] = {
                "foreign_net": _n("外陸資買賣超股數(不含外資自營商)") + _n("外資自營商買賣超股數"),
                "trust_net": _n("投信買賣超股數"),
                "dealer_net": _n("自營商買賣超股數"),
                "total_net": _n("三大法人買賣超股數"),
            }
        print(f"  ✅ 三大法人資料日期: {date_str}（共 {len(flows)} 檔）")
        return flows, date_str

    print("  ❌ 找不到近期三大法人資料")
    return {}, None


def download_historical(tickers, period=None, max_retries=3):
    """
    分批下載歷史日K數據，失敗批次會重試（最多 max_retries 次，間隔遞增）。
    回傳 dict: { ticker: DataFrame(Open,High,Low,Close,Volume) }
    """
    if period is None:
        period = config.DOWNLOAD_PERIOD

    batch_size = config.DOWNLOAD_BATCH_SIZE
    all_data = {}
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]

    print(f"📥 下載歷史數據... ({len(tickers)} 檔, {len(batches)} 批)")

    for batch_idx, batch in enumerate(tqdm(batches, desc="下載進度")):
        data = None
        for attempt in range(1, max_retries + 1):
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
                if data is not None and not data.empty:
                    break
            except Exception as e:
                tqdm.write(f"  ⚠️ 批次 {batch_idx + 1} 第 {attempt}/{max_retries} 次嘗試失敗: {e}")
            if attempt < max_retries:
                time.sleep(config.DOWNLOAD_DELAY * attempt)

        if data is None or data.empty:
            tqdm.write(f"  ❌ 批次 {batch_idx + 1} 重試 {max_retries} 次後仍無資料，略過本批: {batch}")
        elif len(batch) == 1:
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

        if batch_idx < len(batches) - 1:
            time.sleep(config.DOWNLOAD_DELAY)

    print(f"✅ 成功下載 {len(all_data)} 檔股票數據")
    missing = sorted(set(tickers) - set(all_data.keys()))
    if missing:
        preview = missing[:20]
        suffix = f" ...（共 {len(missing)} 檔）" if len(missing) > 20 else ""
        print(f"⚠️ {len(missing)} 檔未取得歷史數據: {preview}{suffix}")
    print()
    return all_data


def resample_to_weekly(daily_df):
    """
    將日K數據重新取樣為週K。
    若最後一筆日K的星期不是週五，代表本週交易日尚未走完，
    該週的週K只用了部分交易日、不算收完，捨棄最後一筆避免誤判。
    """
    weekly = daily_df.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()
    if len(weekly) > 0 and daily_df.index[-1].weekday() != 4:
        weekly = weekly.iloc[:-1]
    return weekly


def _safe_float(s):
    """安全轉換字串為 float"""
    if not s or s in ("--", "-", "", "X"):
        return 0.0
    try:
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return 0.0
