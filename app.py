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


@st.cache_data(ttl=3600)
def fetch_market_overview(date_str):
    try:
        index_res = requests.get(
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

        margin_res = requests.get(
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

        inst_res = requests.get(
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


@st.cache_data(ttl=10)
def fetch_realtime_taiex():
    try:
        res = requests.get(
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


def render_week_chart(trend_df):
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
        barmode="group",
        legend=dict(orientation="h", yanchor="top", y=-0.15, x=0.5, xanchor="center"),
        height=520,
        margin=dict(t=40, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)


@st.dialog("📈 個股籌碼歷史")
def show_stock_dialog(stock_code, stock_name, latest_date_str):
    st.subheader(f"{stock_name}（{stock_code}）")
    trend_df = fetch_week_trend(stock_code, latest_date_str)
    if len(trend_df) >= 2:
        render_week_chart(trend_df)
    else:
        st.warning("近期交易日資料不足，無法繪製曲線圖。")


# -----------------------------------------------------------------------------
# 3. 主介面渲染
# -----------------------------------------------------------------------------
st.title("📊 三大法人籌碼戰報")

st.sidebar.title("⚙️ 篩選設定")
query_date = st.sidebar.date_input("查詢日期", value=datetime.now(), max_value=datetime.now())
query_datetime = datetime.combine(query_date, datetime.min.time())
is_today = query_date.strftime("%Y%m%d") == datetime.now().strftime("%Y%m%d")

df, trade_date = find_trading_day_on_or_before(query_datetime)

if df is not None:
    display_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    if trade_date != query_date.strftime("%Y%m%d"):
        st.caption(f"資料日期：{display_date}（您選擇的日期非交易日，已自動顯示最近一個交易日資料，來源：台灣證券交易所）")
    else:
        st.caption(f"資料日期：{display_date}（盤後資料，來源：台灣證券交易所）")

    overview = fetch_market_overview(trade_date)

    st.subheader("📌 市場總覽")
    col1, col2 = st.columns(2)

    @st.fragment(run_every=10 if is_today else None)
    def render_taiex_tile():
        realtime = fetch_realtime_taiex() if is_today else None
        if realtime:
            st.metric(
                "大盤指數（即時，約5秒延遲）",
                f"{realtime['收盤指數']:,.2f}",
                delta=f"{realtime['漲跌點數']:+,.2f} 點（{realtime['漲跌百分比']:+.2f}%）",
                delta_color="inverse",
            )
            if not realtime["已開盤"]:
                st.caption("尚未開盤，顯示為前一交易日收盤價")
            else:
                st.caption(f"更新時間：{realtime['時間']}")
        elif overview and overview["taiex"]:
            taiex = overview["taiex"]
            st.metric(
                "大盤指數（加權指數，收盤）",
                f"{taiex['收盤指數']:,.2f}",
                delta=f"{taiex['漲跌點數']:+,.2f} 點（{taiex['漲跌百分比']:+.2f}%）",
                delta_color="inverse",
            )
        else:
            st.metric("大盤指數（加權指數）", "查無資料")

    with col1:
        render_taiex_tile()
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

    st.divider()

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
