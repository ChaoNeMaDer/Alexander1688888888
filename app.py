import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
WEEK_TRADING_DAYS = 5


def to_num(value):
    return pd.to_numeric(str(value).replace(",", ""), errors="coerce")


# -----------------------------------------------------------------------------
# 2. 數據抓取：證交所「三大法人買賣超日報」+「每日收盤行情」
#    以單一交易日為單位快取，主排行榜與週曲線圖共用同一份快取
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_day_data(date_str):
    try:
        inst_res = requests.get(
            f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALL",
            headers=HEADERS, timeout=10
        )
        inst_json = inst_res.json()
        if inst_json.get("stat") != "OK" or not inst_json.get("data"):
            return None

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
            return None

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
        return merged
    except Exception:
        return None


def find_trading_day_on_or_before(target_date, max_lookback_days=10):
    for i in range(max_lookback_days):
        date_str = (target_date - timedelta(days=i)).strftime("%Y%m%d")
        day_df = fetch_day_data(date_str)
        if day_df is not None:
            return day_df, date_str
    return None, None


def fetch_week_trend(stock_code, latest_date_str, trading_days=WEEK_TRADING_DAYS, max_lookback_days=14):
    base_date = datetime.strptime(latest_date_str, "%Y%m%d")
    records = []
    for i in range(max_lookback_days):
        date_str = (base_date - timedelta(days=i)).strftime("%Y%m%d")
        day_df = fetch_day_data(date_str)
        if day_df is None:
            continue
        row = day_df[day_df["股票代號"] == stock_code]
        if not row.empty:
            r = row.iloc[0]
            records.append({
                "日期": f"{date_str[4:6]}/{date_str[6:]}",
                "收盤價": r["收盤價"],
                "外資買賣超(張)": r["外資買賣超"] / 1000,
                "投信買賣超(張)": r["投信買賣超"] / 1000,
                "自營商買賣超(張)": r["自營商買賣超"] / 1000,
            })
        if len(records) >= trading_days:
            break
    records.reverse()
    return pd.DataFrame(records)


def render_week_chart(trend_df, stock_code, stock_name):
    bar_specs = [
        ("外資買賣超(張)", "外資", "#e67e22"),
        ("投信買賣超(張)", "投信", "#3498db"),
        ("自營商買賣超(張)", "自營商", "#9b59b6"),
    ]
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
        row_heights=[0.55, 0.45],
        subplot_titles=("三大法人買賣超(張)", "收盤價"),
    )
    for col, label, color in bar_specs:
        fig.add_trace(
            go.Bar(x=trend_df["日期"], y=trend_df[col], name=label, marker_color=color),
            row=1, col=1
        )
    fig.add_trace(
        go.Scatter(
            x=trend_df["日期"], y=trend_df["收盤價"],
            name="收盤價", mode="lines+markers", line=dict(color="#2c3e50", width=3)
        ),
        row=2, col=1
    )
    fig.update_layout(
        title=f"{stock_name}（{stock_code}）近一週籌碼與股價",
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
        height=520,
        margin=dict(t=90),
    )
    st.plotly_chart(fig, use_container_width=True)


@st.dialog("📈 個股籌碼歷史")
def show_stock_dialog(stock_code, stock_name, latest_date_str):
    st.subheader(f"{stock_name}（{stock_code}）")
    trend_df = fetch_week_trend(stock_code, latest_date_str)
    if len(trend_df) >= 2:
        render_week_chart(trend_df, stock_code, stock_name)
    else:
        st.warning("近期交易日資料不足，無法繪製曲線圖。")


# -----------------------------------------------------------------------------
# 3. 主介面渲染
# -----------------------------------------------------------------------------
st.title("📊 三大法人籌碼戰報")

st.sidebar.title("⚙️ 篩選設定")
query_date = st.sidebar.date_input("查詢日期", value=datetime.now(), max_value=datetime.now())
query_datetime = datetime.combine(query_date, datetime.min.time())

df, trade_date = find_trading_day_on_or_before(query_datetime)

if df is not None:
    display_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    if trade_date != query_date.strftime("%Y%m%d"):
        st.caption(f"資料日期：{display_date}（您選擇的日期非交易日，已自動顯示最近一個交易日資料，來源：台灣證券交易所）")
    else:
        st.caption(f"資料日期：{display_date}（盤後資料，來源：台灣證券交易所）")

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

    if "dialog_last_selection" not in st.session_state:
        st.session_state.dialog_last_selection = {}

    def render_ranking(data, ascending, table_key):
        # key 帶入所有篩選條件，任一條件變動就視為新表格，自動清除舊的勾選
        widget_key = f"{table_key}|{inst_type}|{top_n}|{keyword}|{trade_date}"
        table = data.sort_values(inst_type, ascending=ascending).head(top_n).copy()
        table["買賣超(張)"] = (table[inst_type] / 1000).round(0).astype("Int64")
        table["收盤價_display"] = table["收盤價"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
        table["成交量(張)"] = (table["成交股數"] / 1000).round(0).astype("Int64")
        display_cols = ["股票代號", "股票名稱", "買賣超(張)", "收盤價_display", "成交量(張)"]
        event = st.dataframe(
            table[display_cols].rename(columns={"收盤價_display": "收盤價"}),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=widget_key,
        )
        selected_rows = event.selection.rows if event and event.selection else []
        if selected_rows:
            picked = table.iloc[selected_rows[0]]
            code, name = picked["股票代號"], picked["股票名稱"]
            # 每個表格各自記錄自己上次選取的股票，避免另一個分頁殘留的選取狀態被誤判為新選取
            if st.session_state.dialog_last_selection.get(widget_key) != code:
                st.session_state.dialog_last_selection[widget_key] = code
                show_stock_dialog(code, name, trade_date)

    st.caption("💡 點選下方表格中的一列，即可跳出該股票近一週的股價與法人買賣超曲線圖")

    tab_buy, tab_sell = st.tabs(["🟢 買超排行", "🔴 賣超排行"])
    with tab_buy:
        render_ranking(filtered[filtered[inst_type] > 0], ascending=False, table_key="table_buy")
    with tab_sell:
        render_ranking(filtered[filtered[inst_type] < 0], ascending=True, table_key="table_sell")

else:
    st.error(f"⚠️ 查無 {query_date.strftime('%Y-%m-%d')} 前後的三大法人籌碼資料，請換一個日期再試。")
