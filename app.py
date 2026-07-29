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


def to_num(value):
    return pd.to_numeric(str(value).replace(",", ""), errors="coerce")


# -----------------------------------------------------------------------------
# 2. 數據抓取：證交所「三大法人買賣超日報」+「每日收盤行情」
#    找不到當日資料（假日／未開盤）時往前尋找最近一個交易日
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_institutional_chips(max_lookback_days=10):
    for i in range(max_lookback_days):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            inst_res = requests.get(
                f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALL",
                headers=HEADERS, timeout=10
            )
            inst_json = inst_res.json()
            if inst_json.get("stat") != "OK" or not inst_json.get("data"):
                continue

            price_res = requests.get(
                f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json",
                headers=HEADERS, timeout=10
            )
            price_json = price_res.json()
            price_table = next(
                (t for t in price_json.get("tables", []) if "每日收盤行情" in (t.get("title") or "")),
                None
            )
            if not price_table:
                continue

            inst_df = pd.DataFrame(inst_json["data"], columns=inst_json["fields"])
            inst_df["外資買賣超"] = (
                inst_df["外陸資買賣超股數(不含外資自營商)"].map(to_num)
                + inst_df["外資自營商買賣超股數"].map(to_num)
            )
            inst_df["投信買賣超"] = inst_df["投信買賣超股數"].map(to_num)
            inst_df["自營商買賣超"] = inst_df["自營商買賣超股數"].map(to_num)
            inst_df["三大法人合計"] = inst_df["三大法人買賣超股數"].map(to_num)
            inst_df = inst_df.rename(columns={"證券代號": "股票代號", "證券名稱": "股票名稱"})
            inst_df = inst_df[["股票代號", "股票名稱", "外資買賣超", "投信買賣超", "自營商買賣超", "三大法人合計"]]
            inst_df["股票名稱"] = inst_df["股票名稱"].str.strip()

            price_df = pd.DataFrame(price_table["data"], columns=price_table["fields"])
            price_df = price_df.rename(columns={"證券代號": "股票代號"})[["股票代號", "收盤價", "成交股數"]]
            price_df["收盤價"] = price_df["收盤價"].map(to_num)
            price_df["成交股數"] = price_df["成交股數"].map(to_num)

            merged = inst_df.merge(price_df, on="股票代號", how="left")
            # T86 報表含權證等非個股標的，僅保留有實際收盤價／成交量的股票與ETF
            merged = merged.dropna(subset=["收盤價"]).reset_index(drop=True)
            return merged, date_str
        except Exception:
            continue
    return None, None


# -----------------------------------------------------------------------------
# 3. 主介面渲染
# -----------------------------------------------------------------------------
st.title("📊 三大法人籌碼戰報")

df, trade_date = fetch_institutional_chips()

if df is not None:
    display_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    st.caption(f"資料日期：{display_date}（盤後資料，來源：台灣證券交易所）")

    st.sidebar.title("⚙️ 篩選設定")
    inst_type = st.sidebar.selectbox(
        "法人別", ["三大法人合計", "外資買賣超", "投信買賣超", "自營商買賣超"]
    )
    top_n = st.sidebar.selectbox("顯示筆數", [10, 20, 30, 50], index=1)
    keyword = st.sidebar.text_input("搜尋股票代號／名稱", "")

    filtered = df
    if keyword:
        filtered = filtered[
            filtered["股票代號"].str.contains(keyword, case=False, na=False)
            | filtered["股票名稱"].str.contains(keyword, case=False, na=False)
        ]

    def render_ranking(data, ascending):
        table = data.sort_values(inst_type, ascending=ascending).head(top_n).copy()
        table["買賣超(張)"] = (table[inst_type] / 1000).round(0).astype("Int64")
        table["收盤價"] = table["收盤價"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
        table["成交量(張)"] = (table["成交股數"] / 1000).round(0).astype("Int64")
        st.dataframe(
            table[["股票代號", "股票名稱", "買賣超(張)", "收盤價", "成交量(張)"]],
            use_container_width=True,
            hide_index=True,
        )

    tab_buy, tab_sell = st.tabs(["🟢 買超排行", "🔴 賣超排行"])
    with tab_buy:
        render_ranking(filtered[filtered[inst_type] > 0], ascending=False)
    with tab_sell:
        render_ranking(filtered[filtered[inst_type] < 0], ascending=True)

else:
    st.error("⚠️ 無法取得三大法人籌碼資料，請稍後再試。")
