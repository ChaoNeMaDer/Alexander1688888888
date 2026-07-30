import os
import glob
import json
import streamlit as st
import pandas as pd

# -----------------------------------------------------------------------------
# 1. 頁面基本設定
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="箱波均戰法選股",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stock_screener", "output")


# -----------------------------------------------------------------------------
# 2. 讀取最新一份預先產生的選股報表（由 GitHub Actions 排程執行 auto_run.py 產生）
# -----------------------------------------------------------------------------
def load_latest_report():
    if not os.path.isdir(OUTPUT_DIR):
        return None
    json_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "results_*.json")))
    if not json_files:
        return None
    latest_path = json_files[-1]
    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    data["_path"] = latest_path
    return data


# -----------------------------------------------------------------------------
# 3. 主介面渲染
# -----------------------------------------------------------------------------
st.title("📈 箱波均戰法選股")

report = load_latest_report()

if report is None:
    st.info("尚無選股報表，請等待排程執行後再回來查看（每個交易日收盤後自動掃描）。")
else:
    date_str = report["date"]
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    results = report["results"]
    st.caption(f"資料日期：{display_date}（本日共掃描 {report['total_scanned']} 檔股票，符合條件 {len(results)} 檔）")

    if not results:
        st.warning("今日無符合「週K買進中 + 日K新買進訊號」的股票。")
    else:
        df = pd.DataFrame(results)
        df["tv_link"] = "https://www.tradingview.com/chart/?symbol=TWSE%3A" + df["code"]

        # 舊版報表可能沒有三大法人欄位，補上避免後面存取出錯
        for col in ("foreign_lots", "trust_lots", "dealer_lots", "total_lots"):
            if col not in df.columns:
                df[col] = None

        st.sidebar.title("⚙️ 篩選設定")
        reason_options = sorted(df["daily_buy_reason"].dropna().unique().tolist())
        selected_reasons = st.sidebar.multiselect("日K買進原因", reason_options, default=reason_options)
        keyword = st.sidebar.text_input("搜尋股票代號／名稱", "")

        inst_filter_options = {
            "不篩選（顯示全部技術面符合的股票）": None,
            "三大法人合計買超": "total_lots",
            "外資買超": "foreign_lots",
            "投信買超": "trust_lots",
            "自營商買超": "dealer_lots",
            "外資、投信、自營商皆買超": "__all__",
        }
        selected_inst_label = st.sidebar.selectbox("法人篩選依據", list(inst_filter_options.keys()))
        inst_key = inst_filter_options[selected_inst_label]

        filtered = df[df["daily_buy_reason"].isin(selected_reasons)]
        if keyword:
            filtered = filtered[
                filtered["code"].str.contains(keyword, case=False, na=False)
                | filtered["name"].str.contains(keyword, case=False, na=False)
            ]

        if inst_key == "__all__":
            filtered = filtered[
                (filtered["foreign_lots"] > 0) & (filtered["trust_lots"] > 0) & (filtered["dealer_lots"] > 0)
            ]
        elif inst_key is not None:
            filtered = filtered[filtered[inst_key] > 0]

        inst_date = results[0].get("inst_date") if results else None
        if inst_date:
            inst_display_date = f"{inst_date[:4]}-{inst_date[4:6]}-{inst_date[6:]}"
            st.caption(f"三大法人買賣超資料日期：{inst_display_date}（僅涵蓋上市股票）")

        display_cols = {
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
            "tv_link": "TradingView",
        }
        table = filtered[list(display_cols.keys())].rename(columns=display_cols)

        st.dataframe(
            table,
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

        st.caption(f"共 {len(table)} 檔符合篩選條件（技術面符合 {len(df)} 檔）")

        st.divider()
        st.subheader("📥 下載原始報表")
        col1, col2 = st.columns(2)
        for col, ext, label, mime in (
            (col1, "html", "HTML 報表", "text/html"),
            (col2, "xlsx", "Excel 報表", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ):
            report_path = os.path.join(OUTPUT_DIR, f"report_{date_str}.{ext}")
            if os.path.exists(report_path):
                with open(report_path, "rb") as f:
                    col.download_button(
                        f"下載{label}",
                        data=f.read(),
                        file_name=f"report_{date_str}.{ext}",
                        mime=mime,
                    )
            else:
                col.caption(f"{label}不存在")
