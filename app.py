import glob
import json
import os
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# 1. 頁面基本設定與 PWA (iOS App) Meta 標籤注入
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="法人籌碼戰報",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入 iOS 全螢幕與桌面圖示設定 (PWA Meta Tags)
pwa_meta_html = """
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="法人籌碼">
    <link rel="apple-touch-icon" href="https://em-content.zobj.net/source/apple/391/bar-chart_1f4ca.png">
    <style>
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 2rem !important;
        }
    </style>
"""
st.components.v1.html(pwa_meta_html, height=0)

HEADERS = {"User-Agent": "Mozilla/5.0"}
SESSION = requests.Session()
SCREENER_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_screener", "output")


def to_num(value):
    return pd.to_numeric(str(value).replace(",", ""), errors="coerce")


# -----------------------------------------------------------------------------
# 2. 數據抓取：證交所「大盤指數」+「融資餘額」+「三大法人買賣超」
#    以單一交易日為單位快取
# -----------------------------------------------------------------------------
def _fetch_market_overview_uncached(date_str):
    try:
        index_res = SESSION.get(
            f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json",
            headers=HEADERS, timeout=10
        )
        index_json = index_res.json()
        index_table = next(
            (t for t in index_json.get("tables", []) if "價格指數" in (t.get("title") or "")),
            None
        )
        taiex = None
        if index_table:
            fields = index_table["fields"]
            for row in index_table["data"]:
                if row[fields.index("指數")] != "發行量加權股價指數":
                    continue
                sign = -1 if "color:green" in row[fields.index("漲跌(+/-)")] else 1
                taiex = {
                    "收盤指數": to_num(row[fields.index("收盤指數")]),
                    "漲跌點數": to_num(row[fields.index("漲跌點數")]) * sign,
                    "漲跌百分比": to_num(row[fields.index("漲跌百分比(%)")]),  # 已內含正負號
                }
                break

        margin_res = SESSION.get(
            f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={date_str}&selectType=ALL&response=json",
            headers=HEADERS, timeout=10
        )
        margin_json = margin_res.json()
        credit_table = next(
            (t for t in margin_json.get("tables", []) if "信用交易統計" in (t.get("title") or "")),
            None
        )
        margin_balance = None
        if credit_table:
            fields = credit_table["fields"]
            for row in credit_table["data"]:
                if row[0] == "融資金額(仟元)":
                    margin_balance = to_num(row[fields.index("今日餘額")]) * 1000  # 仟元 -> 元
                    break

        inst_res = SESSION.get(
            f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&dayDate={date_str}&type=day",
            headers=HEADERS, timeout=10
        )
        inst_json = inst_res.json()
        institutional = {}
        if inst_json.get("stat") == "OK":
            net = {row[0]: to_num(row[3]) for row in inst_json["data"]}
            institutional = {
                "外資": net.get("外資及陸資(不含外資自營商)", 0),
                "投信": net.get("投信", 0),
                "自營商": net.get("自營商(自行買賣)", 0) + net.get("自營商(避險)", 0),
                "合計": net.get("合計", 0),
            }

        if taiex is None and margin_balance is None and not institutional:
            return None
        return {"taiex": taiex, "margin_balance": margin_balance, "institutional": institutional}
    except Exception:
        return None


@st.cache_data(ttl=3600)
def _fetch_market_overview_cached_long(date_str):
    return _fetch_market_overview_uncached(date_str)


@st.cache_data(ttl=300)
def _fetch_market_overview_cached_short(date_str):
    return _fetch_market_overview_uncached(date_str)


def fetch_market_overview(date_str):
    # 融資餘額（MI_MARGN）公布時間常晚於大盤指數／三大法人，當天資料剛好卡在
    # 「已可查詢但 TWSE 尚未公布」的情況很常見；用短 TTL 讓使用者不用等滿 1 小時
    # 就能看到剛公布的資料。非當天的歷史資料已定案，維持長 TTL 即可。
    if date_str == datetime.now().strftime("%Y%m%d"):
        return _fetch_market_overview_cached_short(date_str)
    return _fetch_market_overview_cached_long(date_str)


def find_overview_trading_day(max_lookback_days=10):
    """
    自動找「今天如果有資料就用今天，沒有就往前找最近一個有資料的交易日」。
    有資料的判斷標準跟 fetch_market_overview 一致：大盤指數／融資餘額／三大法人
    三者只要有任一項不是 None，就視為當天資料已可用。
    """
    base_date = datetime.now()
    for i in range(max_lookback_days):
        date_str = (base_date - timedelta(days=i)).strftime("%Y%m%d")
        if fetch_market_overview(date_str) is not None:
            return date_str
    return None


def _fetch_overview_history_uncached(latest_date_str, trading_days=20, max_lookback_days=32):
    base_date = datetime.strptime(latest_date_str, "%Y%m%d")
    date_strs = [(base_date - timedelta(days=i)).strftime("%Y%m%d") for i in range(max_lookback_days)]

    records = []
    for date_str in date_strs:
        day_overview = _fetch_market_overview_uncached(date_str)
        if day_overview is None or day_overview["margin_balance"] is None or not day_overview["institutional"]:
            continue
        inst = day_overview["institutional"]
        records.append({
            "日期": date_str,
            "外資": inst.get("外資"),
            "投信": inst.get("投信"),
            "自營商": inst.get("自營商"),
            "合計": inst.get("合計"),
            "融資餘額": day_overview["margin_balance"],
        })
        if len(records) >= trading_days:
            break
    records.reverse()
    return pd.DataFrame(records)


@st.cache_data(ttl=3600)
def _fetch_overview_history_cached_long(latest_date_str, trading_days=20, max_lookback_days=32):
    return _fetch_overview_history_uncached(latest_date_str, trading_days, max_lookback_days)


@st.cache_data(ttl=300)
def _fetch_overview_history_cached_short(latest_date_str, trading_days=20, max_lookback_days=32):
    return _fetch_overview_history_uncached(latest_date_str, trading_days, max_lookback_days)


def fetch_overview_history(latest_date_str, trading_days=20, max_lookback_days=32):
    # 跟 fetch_market_overview 用一樣的今日短快取／非今日長快取邏輯，
    # 避免「總覽已經有今天的融資餘額，異常摘要卻還當作今天沒資料」的不同步狀況。
    if latest_date_str == datetime.now().strftime("%Y%m%d"):
        return _fetch_overview_history_cached_short(latest_date_str, trading_days, max_lookback_days)
    return _fetch_overview_history_cached_long(latest_date_str, trading_days, max_lookback_days)


def _compute_streak(series, min_days):
    if series is None or len(series) < min_days:
        return None
    values = list(series.iloc[::-1])
    sign = 1 if values[0] >= 0 else -1
    streak = 0
    for v in values:
        if (v >= 0) == (sign == 1):
            streak += 1
        else:
            break
    if streak < min_days:
        return None
    return {"sign": sign, "streak": streak, "total": sum(values[:streak])}


def detect_anomalies(history_df, z_threshold=2.0, streak_min_days=3):
    if history_df is None or len(history_df) < 6:
        return []
    anomalies = []
    today = history_df.iloc[-1]
    baseline = history_df.iloc[:-1]

    for col, label in [("外資", "外資"), ("投信", "投信"), ("自營商", "自營商"), ("合計", "三大法人合計")]:
        mean, std = baseline[col].mean(), baseline[col].std()
        if std and std > 0:
            z = (today[col] - mean) / std
            if abs(z) >= z_threshold:
                direction = "買超" if today[col] >= 0 else "賣超"
                anomalies.append({
                    "type": "institutional",
                    "entity": label,
                    "direction": direction,
                    "today_value": today[col],
                    "mean": mean,
                    "z": z,
                    "baseline_n": len(baseline),
                    "label": f"{label}{direction}金額異常",
                    "summary": (
                        f"今日 {today[col] / 1e8:+.2f} 億元，"
                        f"明顯偏離近{len(baseline)}日均值（{mean / 1e8:+.2f} 億元），z-score={z:+.1f}"
                    ),
                })

    margin_diff = history_df["融資餘額"].diff().dropna()
    if len(margin_diff) >= 6:
        today_diff, baseline_diff = margin_diff.iloc[-1], margin_diff.iloc[:-1]
        mean, std = baseline_diff.mean(), baseline_diff.std()
        if std and std > 0:
            z = (today_diff - mean) / std
            if abs(z) >= z_threshold:
                direction = "增加" if today_diff >= 0 else "減少"
                anomalies.append({
                    "type": "margin",
                    "direction": direction,
                    "today_value": today_diff,
                    "mean": mean,
                    "z": z,
                    "baseline_n": len(baseline_diff),
                    "label": f"融資餘額單日{direction}異常",
                    "summary": (
                        f"單日變動 {today_diff / 1e8:+.2f} 億元，"
                        f"明顯偏離近期平均，z-score={z:+.1f}"
                    ),
                })

    for col, label in [("外資", "外資"), ("投信", "投信"), ("自營商", "自營商"), ("合計", "三大法人合計")]:
        s = _compute_streak(history_df[col], streak_min_days)
        if s:
            direction = "買超" if s["sign"] >= 0 else "賣超"
            anomalies.append({
                "type": "streak_institutional",
                "entity": label,
                "direction": direction,
                "streak": s["streak"],
                "total": s["total"],
                "label": f"{label}連續{s['streak']}日{direction}",
                "summary": f"已連續 {s['streak']} 個交易日{direction}，合計 {s['total'] / 1e8:+.2f} 億元",
            })

    s = _compute_streak(margin_diff, streak_min_days)
    if s:
        direction = "增加" if s["sign"] >= 0 else "減少"
        anomalies.append({
            "type": "streak_margin",
            "direction": direction,
            "streak": s["streak"],
            "total": s["total"],
            "label": f"融資餘額連續{s['streak']}日{direction}",
            "summary": f"已連續 {s['streak']} 個交易日{direction}，合計變動 {s['total'] / 1e8:+.2f} 億元",
        })
    return anomalies


def _describe_context(index_change, inst_net):
    context = []
    if index_change is not None:
        context.append(f"大盤當日{'上漲' if index_change >= 0 else '下跌'} {abs(index_change):.2f} 點")
    if inst_net is not None:
        context.append(f"三大法人合計{'買超' if inst_net >= 0 else '賣超'} {abs(inst_net) / 1e8:.2f} 億元")
    return context


def explain_institutional(a, index_change, inst_net):
    entity, direction = a["entity"], a["direction"]
    entity_def = {
        "外資": "外資（含外國機構投資人與陸資）",
        "投信": "國內投信基金",
        "自營商": "證券自營商（用公司自有資金操作）",
        "三大法人合計": "外資、投信、自營商三者加總",
    }.get(entity, entity)

    lines = [
        f"**{entity}是什麼** {entity_def}，是市場觀察機構籌碼動向的三大主力之一。",
        (
            f"**今天發生了什麼** {entity}今日{direction} {abs(a['today_value']) / 1e8:.2f} 億元，"
            f"相較近{a['baseline_n']}日平均（{a['mean'] / 1e8:+.2f} 億元）明顯偏離，z-score={a['z']:+.1f}，"
            "統計上代表這幾乎不是隨機波動，而是方向性很強的操作。"
        ),
    ]
    if direction == "買超":
        lines.append("**可能成因** 評價偏低轉為加碼、特定族群或政策題材帶動買盤集中，或是被動式資金移動（如 ETF 成分股調整、期現貨對沖）。")
    else:
        lines.append("**可能成因** 獲利了結、風險趨避轉為調節持股、特定產業基本面轉差引發出貨，或是被動式調整（如 ETF 成分股汰換）帶來的賣壓。")

    context = _describe_context(index_change, inst_net if entity != "三大法人合計" else None)
    if context:
        lines.append(f"**同一天的其他訊號** {'、'.join(context)}。")

    lines.append("**對決策的意義** 單一法人買賣超金額異常，代表籌碼出現集中且不尋常的動向，值得留意是否延續；但單一天的數字不足以判斷趨勢是否成立，建議搭配後續 1-2 個交易日的同一指標觀察是否同方向持續。")
    return "\n\n".join(lines)


def explain_margin(a, index_change, inst_net):
    direction = a["direction"]
    lines = [
        "**融資餘額是什麼** 融資＝投資人跟券商借錢買股票（放大槓桿）。融資餘額就是全市場「借錢買股票、還沒還」的總金額，是散戶槓桿／投機情緒的指標。",
        (
            f"**今天發生了什麼** 融資餘額單日{direction} {abs(a['today_value']) / 1e8:.2f} 億元，"
            f"明顯偏離近期平均變動幅度，z-score={a['z']:+.1f}，統計上代表這不是正常的漲跌互抵，是異常快的槓桿變化。"
        ),
    ]
    if direction == "減少":
        lines.append(
            "**可能成因**\n"
            "1. 融資斷頭（被動）：股價下跌時融資戶被追繳保證金，繳不出來就被強制砍倉。\n"
            "2. 主動去槓桿：投資人自己看壞後市，提前平倉還錢降低風險。"
        )
    else:
        lines.append("**可能成因** 投資人大舉加碼槓桿買進，可能是追高情緒濃厚，也可能是逢低加碼、對後市偏樂觀。")

    context = _describe_context(index_change, inst_net)
    if context:
        aligned = (
            index_change is not None and inst_net is not None
            and ((index_change < 0 and inst_net < 0 and direction == "減少")
                 or (index_change > 0 and inst_net > 0 and direction == "增加"))
        )
        note = " 三個訊號同方向出現，代表這是一次有分量的行情變化，可信度較高。" if aligned else ""
        lines.append(f"**同一天的其他訊號** {'、'.join(context)}。{note}")

    if direction == "減少":
        lines.append("**對決策的意義** 融資餘額異常減少不是單純多空訊號，而是值得多看一眼的警示——如果接下來融資持續下滑但股價止跌，常被解讀為浮額出清、短線有望技術性反彈；如果融資持續減少、股價也持續破底，代表去槓桿可能還沒結束。")
    else:
        lines.append("**對決策的意義** 融資餘額異常增加代表市場槓桿快速堆高，短線追價意願強，但也墊高了下跌時的賣壓風險（一旦股價回檔，更容易觸發連鎖斷頭）。")
    return "\n\n".join(lines)


def explain_streak_institutional(a, index_change, inst_net):
    entity, direction = a["entity"], a["direction"]
    entity_def = {
        "外資": "外資（含外國機構投資人與陸資）",
        "投信": "國內投信基金",
        "自營商": "證券自營商（用公司自有資金操作）",
        "三大法人合計": "外資、投信、自營商三者加總",
    }.get(entity, entity)

    lines = [
        f"**{entity}是什麼** {entity_def}。",
        (
            f"**今天發生了什麼** {entity}已經連續 {a['streak']} 個交易日{direction}，"
            f"合計 {a['total'] / 1e8:+.2f} 億元，代表這不是單日的偶發操作，而是持續一段時間的方向。"
        ),
    ]
    if direction == "買超":
        lines.append("**可能成因** 對後市偏樂觀、逢低分批加碼，或特定產業／政策題材帶動的中期布局。")
    else:
        lines.append("**可能成因** 對後市轉為保守、分批調節持股，或特定產業基本面轉弱引發的持續調節。")

    context = _describe_context(index_change, inst_net if entity != "三大法人合計" else None)
    if context:
        lines.append(f"**同一天的其他訊號** {'、'.join(context)}。")

    lines.append("**對決策的意義** 連續多日同方向，比單日數字更有持續性，通常值得留意是否會延續成一段趨勢；但也要留意何時出現方向反轉（例如轉買為賣），這往往是趨勢可能結束的訊號。")
    return "\n\n".join(lines)


def explain_streak_margin(a, index_change, inst_net):
    direction = a["direction"]
    lines = [
        "**融資餘額是什麼** 融資＝投資人跟券商借錢買股票（放大槓桿）。融資餘額就是全市場「借錢買股票、還沒還」的總金額，是散戶槓桿／投機情緒的指標。",
        (
            f"**今天發生了什麼** 融資餘額已經連續 {a['streak']} 個交易日{direction}，"
            f"合計變動 {a['total'] / 1e8:+.2f} 億元，代表槓桿部位正在持續同方向變化，不是單日雜訊。"
        ),
    ]
    if direction == "減少":
        lines.append("**可能成因** 股價持續下跌、融資戶陸續被追繳／斷頭，也可能是投資人主動、有紀律地連日去槓桿。")
    else:
        lines.append("**可能成因** 股價持續上漲、投資人持續加碼追價，槓桿部位持續堆高。")

    context = _describe_context(index_change, inst_net)
    if context:
        lines.append(f"**同一天的其他訊號** {'、'.join(context)}。")

    if direction == "減少":
        lines.append("**對決策的意義** 連續多日去槓桿如果伴隨股價落底、跌勢趨緩，通常代表浮額出清接近尾聲；但如果股價持續破底，代表去槓桿壓力可能還沒完全反映完。")
    else:
        lines.append("**對決策的意義** 連續多日槓桿堆高，代表市場追價情緒濃厚；一旦出現轉弱訊號，回檔時容易因為集中的融資部位而放大賣壓，需留意風險。")
    return "\n\n".join(lines)


@st.dialog("📊 異常訊號解析")
def show_anomaly_dialog(anomaly, index_change, inst_net):
    st.subheader(anomaly["label"])
    st.caption(anomaly["summary"])
    explainers = {
        "institutional": explain_institutional,
        "margin": explain_margin,
        "streak_institutional": explain_streak_institutional,
        "streak_margin": explain_streak_margin,
    }
    st.markdown(explainers[anomaly["type"]](anomaly, index_change, inst_net))


@st.cache_data(ttl=10)
def fetch_realtime_taiex():
    try:
        res = SESSION.get(
            "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw",
            headers=HEADERS, timeout=5
        )
        rows = res.json().get("msgArray", [])
        if not rows:
            return None
        row = rows[0]
        prev_close = to_num(row.get("y"))
        z = row.get("z")
        is_open = z not in (None, "-")
        current = to_num(z) if is_open else prev_close
        if pd.isna(current) or pd.isna(prev_close):
            return None
        change = current - prev_close
        return {
            "收盤指數": current,
            "漲跌點數": change,
            "漲跌百分比": (change / prev_close * 100) if prev_close else 0,
            "時間": row.get("t"),
            "已開盤": is_open,
        }
    except Exception:
        return None


def render_stat_tile(label, amount_ntd):
    yi = amount_ntd / 1e8
    color = "#e03131" if yi >= 0 else "#2f9e44"
    direction = "買超" if yi >= 0 else "賣超"
    st.markdown(
        f"""
        <div style="line-height:1.3;">
            <div style="font-size:0.875rem;color:gray;">{label}（{direction}）</div>
            <div style="font-size:1.6rem;font-weight:600;color:{color};">{yi:+,.2f} 億元</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_market_signal(index_change, inst_net_ntd, anomalies=None):
    if index_change is None or inst_net_ntd is None:
        return
    index_up = index_change >= 0
    inst_buy = inst_net_ntd >= 0
    if index_up and inst_buy:
        color, label, desc = "#e03131", "多方一致", "大盤上漲，三大法人同步買超"
    elif not index_up and not inst_buy:
        color, label, desc = "#2f9e44", "空方一致", "大盤下跌，三大法人同步賣超"
    elif index_up and not inst_buy:
        color, label, desc = "#f08c00", "上漲但法人賣超", "指數上漲，三大法人卻賣超，留意上漲力道是否穩固"
    else:
        color, label, desc = "#f08c00", "下跌但法人買超", "指數下跌，三大法人卻買超，留意是否醞釀反彈"

    watch_html = ""
    if anomalies:
        items = "".join(f"<li>{a['label']}</li>" for a in anomalies[:4])
        watch_html = f"""
        <div style="margin-top:0.5rem; padding-top:0.5rem; border-top:1px solid rgba(128,128,128,0.25);">
            <span style="font-size:0.85rem; color:gray;">📋 今日應注意事項：</span>
            <ul style="margin:0.25rem 0 0 1.2rem; padding:0; font-size:0.85rem; color:gray;">
                {items}
            </ul>
        </div>
        """

    st.markdown(
        f"""
        <div style="border-left:6px solid {color}; background:rgba(128,128,128,0.08);
                    padding:0.75rem 1rem; border-radius:6px; margin-bottom:1rem;">
            <span style="font-size:1.15rem; font-weight:700; color:{color};">🚦 {label}</span>
            <span style="font-size:0.9rem; color:gray; margin-left:0.6rem;">{desc}</span>
            {watch_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# 2.5 讀取箱波均戰法選股報表（由 GitHub Actions 排程執行 auto_run.py 產生）
# -----------------------------------------------------------------------------
def load_latest_screener_report():
    if not os.path.isdir(SCREENER_OUTPUT_DIR):
        return None
    json_files = sorted(glob.glob(os.path.join(SCREENER_OUTPUT_DIR, "results_*.json")))
    if not json_files:
        return None
    try:
        with open(json_files[-1], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# -----------------------------------------------------------------------------
# 3. 主介面渲染
# -----------------------------------------------------------------------------
st.title("📊 三大法人籌碼戰報")

trade_date = find_overview_trading_day()

if trade_date is None:
    st.error("⚠️ 查無近期的三大法人籌碼資料，請稍後再試。")
else:
    today_str = datetime.now().strftime("%Y%m%d")
    display_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    if trade_date != today_str:
        st.caption(f"資料日期：{display_date}（今日尚無資料，已自動顯示最近一個交易日資料，來源：台灣證券交易所）")
    else:
        st.caption(f"資料日期：{display_date}（盤後資料，來源：台灣證券交易所）")

    st.subheader("📌 市場總覽")

    @st.fragment(run_every=10)
    def render_market_overview():
        # overview 要寫在 fragment 裡面才會跟著 run_every 的定時器重跑；
        # 寫在 fragment 外面的話只有整頁重跑才會重新抓取，10 秒的自動更新
        # 就只會刷新即時指數，不會刷新這裡的資料。
        overview = fetch_market_overview(trade_date)
        realtime = fetch_realtime_taiex()

        # 訊號燈號／異常摘要都是根據 trade_date（三大法人資料實際涵蓋的交易日）判讀，
        # 必須跟「同一天」的大盤漲跌對照。三大法人統計要收盤後才公布，
        # 盤中不能拿當下的即時指數去配前一個交易日的法人資料，否則兩者根本不是同一天的事。
        trade_date_index_change = overview["taiex"]["漲跌點數"] if overview and overview["taiex"] else None
        inst_net = overview["institutional"].get("合計") if overview and overview["institutional"] else None

        with st.spinner("正在比對近期資料..."):
            history_df = fetch_overview_history(trade_date)
        anomalies = detect_anomalies(history_df)

        render_market_signal(trade_date_index_change, inst_net, anomalies)
        if realtime and realtime["已開盤"]:
            st.caption(f"🚦 訊號依 {display_date}（最近一個完整交易日）資料判讀，三大法人統計需等收盤後公布")

        col1, col2 = st.columns(2)
        with col1:
            if realtime and realtime["已開盤"]:
                st.metric(
                    "大盤指數（即時，約5秒延遲）",
                    f"{realtime['收盤指數']:,.2f}",
                    delta=f"{realtime['漲跌點數']:+,.2f} 點（{realtime['漲跌百分比']:+.2f}%）",
                    delta_color="inverse",
                )
                st.caption(f"更新時間：{realtime['時間']}")
            elif overview and overview["taiex"]:
                taiex = overview["taiex"]
                st.metric(
                    "大盤指數（加權指數，收盤）",
                    f"{taiex['收盤指數']:,.2f}",
                    delta=f"{taiex['漲跌點數']:+,.2f} 點（{taiex['漲跌百分比']:+.2f}%）",
                    delta_color="inverse",
                )
                st.caption("尚未開盤，顯示為前一交易日收盤價與漲跌")
            else:
                st.metric("大盤指數（加權指數）", "查無資料")
        with col2:
            if overview and overview["margin_balance"] is not None:
                st.metric("融資餘額", f"{overview['margin_balance'] / 1e8:,.2f} 億元")
            else:
                st.metric("融資餘額", "查無資料")

        if overview and overview["institutional"]:
            inst = overview["institutional"]
            c1, c2, c3, c4 = st.columns(4)
            for col, key in zip((c1, c2, c3, c4), ("外資", "投信", "自營商", "合計")):
                with col:
                    render_stat_tile("三大法人合計" if key == "合計" else key, inst[key])
        else:
            st.info("查無三大法人買賣金額資料")

        st.subheader("⚠️ 異常摘要")
        if anomalies:
            for i, a in enumerate(anomalies):
                with st.container(border=True):
                    box_col, btn_col = st.columns([6, 1], vertical_alignment="center")
                    box_col.markdown(f"⚠️ **{a['label']}** — {a['summary']}")
                    if btn_col.button("查看解析", key=f"anomaly_btn_{trade_date}_{i}"):
                        show_anomaly_dialog(a, trade_date_index_change, inst_net)
        else:
            st.caption(f"近{max(len(history_df) - 1, 0)}日比對下，目前無明顯偏離常態的訊號")

    render_market_overview()

    st.divider()

    # ── 箱波均戰法選股結果 ──
    st.subheader("📈 箱波均戰法選股")
    report = load_latest_screener_report()

    if report is None:
        st.info("尚無選股報表，請等待排程執行後再回來查看（每個交易日收盤後自動掃描）。")
    else:
        screener_date = report["date"]
        screener_display_date = f"{screener_date[:4]}-{screener_date[4:6]}-{screener_date[6:]}"
        screener_results = report["results"]
        st.caption(
            f"資料日期：{screener_display_date}"
            f"（本日共掃描 {report['total_scanned']} 檔股票，符合條件 {len(screener_results)} 檔）"
        )

        if not screener_results:
            st.warning("今日無符合「週K買進中 + 日K新買進訊號」的股票。")
        else:
            screener_df = pd.DataFrame(screener_results)
            screener_df["tv_link"] = "https://www.tradingview.com/chart/?symbol=TWSE%3A" + screener_df["code"]

            # 舊版報表可能沒有這些欄位，補上避免後面存取出錯
            for col in (
                "foreign_lots", "trust_lots", "dealer_lots", "total_lots",
                "foreign_streak", "trust_streak", "dealer_streak", "total_streak",
            ):
                if col not in screener_df.columns:
                    screener_df[col] = None

            def _streak_label(streak):
                if not streak:
                    return "-"
                direction = "買超" if streak > 0 else "賣超"
                return f"連續{abs(int(streak))}日{direction}"

            screener_df["籌碼確認"] = screener_df["total_streak"].map(_streak_label)

            st.sidebar.title("⚙️ 箱波均選股篩選")
            reason_options = sorted(screener_df["daily_buy_reason"].dropna().unique().tolist())
            selected_reasons = st.sidebar.multiselect("日K買進原因", reason_options, default=reason_options)
            screener_keyword = st.sidebar.text_input("搜尋股票代號／名稱", "")

            inst_filter_options = {
                "不篩選（顯示全部技術面符合的股票）": None,
                "三大法人合計買超": "total_lots",
                "外資買超": "foreign_lots",
                "投信買超": "trust_lots",
                "自營商買超": "dealer_lots",
                "外資、投信、自營商皆買超": "__all__",
                "三大法人合計連續買超（籌碼確認）": "__streak__",
            }
            selected_inst_label = st.sidebar.selectbox("法人篩選依據", list(inst_filter_options.keys()))
            inst_key = inst_filter_options[selected_inst_label]

            screener_filtered = screener_df[screener_df["daily_buy_reason"].isin(selected_reasons)]
            if screener_keyword:
                screener_filtered = screener_filtered[
                    screener_filtered["code"].str.contains(screener_keyword, case=False, na=False)
                    | screener_filtered["name"].str.contains(screener_keyword, case=False, na=False)
                ]

            if inst_key == "__all__":
                screener_filtered = screener_filtered[
                    (screener_filtered["foreign_lots"] > 0)
                    & (screener_filtered["trust_lots"] > 0)
                    & (screener_filtered["dealer_lots"] > 0)
                ]
            elif inst_key == "__streak__":
                screener_filtered = screener_filtered[screener_filtered["total_streak"] > 0]
            elif inst_key is not None:
                screener_filtered = screener_filtered[screener_filtered[inst_key] > 0]

            screener_inst_date = screener_results[0].get("inst_date") if screener_results else None
            if screener_inst_date:
                screener_inst_display_date = (
                    f"{screener_inst_date[:4]}-{screener_inst_date[4:6]}-{screener_inst_date[6:]}"
                )
                st.caption(f"三大法人買賣超資料日期：{screener_inst_display_date}（僅涵蓋上市股票）")

            screener_display_cols = {
                "code": "代號",
                "name": "名稱",
                "market": "市場",
                "close": "收盤價",
                "change_pct": "漲跌幅(%)",
                "volume_lots": "成交量(張)",
                "daily_buy_reason": "日K買進原因",
                "daily_trend_text": "日K趨勢",
                "weekly_trend_text": "週K趨勢",
                "foreign_lots": "外資買賣超(張)",
                "trust_lots": "投信買賣超(張)",
                "dealer_lots": "自營商買賣超(張)",
                "total_lots": "三大法人合計(張)",
                "籌碼確認": "籌碼確認",
                "tv_link": "TradingView",
            }
            screener_table = screener_filtered[list(screener_display_cols.keys())].rename(columns=screener_display_cols)

            st.dataframe(
                screener_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "收盤價": st.column_config.NumberColumn(format="%.2f"),
                    "漲跌幅(%)": st.column_config.NumberColumn(format="%.2f%%"),
                    "外資買賣超(張)": st.column_config.NumberColumn(format="%d"),
                    "投信買賣超(張)": st.column_config.NumberColumn(format="%d"),
                    "自營商買賣超(張)": st.column_config.NumberColumn(format="%d"),
                    "三大法人合計(張)": st.column_config.NumberColumn(format="%d"),
                    "TradingView": st.column_config.LinkColumn(display_text="看圖"),
                },
            )

            st.caption(f"共 {len(screener_table)} 檔符合篩選條件（技術面符合 {len(screener_df)} 檔）")

            st.divider()
            st.subheader("📥 下載選股原始報表")
            col1, col2 = st.columns(2)
            for col, ext, label, mime in (
                (col1, "html", "HTML 報表", "text/html"),
                (col2, "xlsx", "Excel 報表", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ):
                screener_report_path = os.path.join(SCREENER_OUTPUT_DIR, f"report_{screener_date}.{ext}")
                if os.path.exists(screener_report_path):
                    with open(screener_report_path, "rb") as f:
                        col.download_button(
                            f"下載{label}",
                            data=f.read(),
                            file_name=f"report_{screener_date}.{ext}",
                            mime=mime,
                        )
                else:
                    col.caption(f"{label}不存在")
