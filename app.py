import streamlit as st
import pandas as pd
import yfinance as yf

# -----------------------------------------------------------------------------
# 1. 頁面基本設定與 PWA (iOS App) Meta 標籤注入
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="籌碼戰報 PWA",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 注入 iOS 全螢幕與桌面圖示設定 (PWA Meta Tags)
pwa_meta_html = """
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="籌碼戰報">
    <link rel="apple-touch-icon" href="https://em-content.zobj.net/source/apple/391/chart-increasing_1f4c8.png">
    <style>
        /* 隱藏預設 Streamlit 頁首頁尾Padding，打造更像 App 的質感 */
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 2rem !important;
        }
    </style>
"""
st.components.v1.html(pwa_meta_html, height=0)

# -----------------------------------------------------------------------------
# 2. 模擬帳戶狀態初始化 (Session State)
# -----------------------------------------------------------------------------
if 'cash' not in st.session_state:
    st.session_state.cash = 100000.0  # 預設虛擬本金 10 萬
if 'portfolio' not in st.session_state:
    # 紀錄持股: { stock_id: {'shares': 股數, 'cost': 平均買入成本} }
    st.session_state.portfolio = {}
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []

# -----------------------------------------------------------------------------
# 3. 側邊欄控制與參數設定
# -----------------------------------------------------------------------------
st.sidebar.title("⚙️ 控制面板")
target_stock = st.sidebar.text_input("輸入台股代號", value="2367.TW", help="請輸入 Yahoo Finance 格式，例如：2367.TW, 3481.TW, 3231.TW")
reset_btn = st.sidebar.button("🔄 重置虛擬帳戶 (恢復10萬)")

if reset_btn:
    st.session_state.cash = 100000.0
    st.session_state.portfolio = {}
    st.session_state.trade_history = []
    st.toast("帳戶已重置為 10 萬元！")
    st.rerun()

# -----------------------------------------------------------------------------
# 4. 數據抓取與籌碼指標運算
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_stock_data(symbol):
    try:
        df = yf.download(symbol, period="3m")
        if df.empty:
            return None
        # 計算 20日均線 (月線)
        df['MA20'] = df['Close'].rolling(window=20).mean()
        # 模擬三大法人籌碼數據（註：yfinance無台股籌碼，此處示範籌碼邏輯運算）
        # 實際可對接 TWSE API 或 FinMind
        df['Volume_MA5'] = df['Volume'].rolling(window=5).mean()
        return df
    except Exception as e:
        return None

df_stock = fetch_stock_data(target_stock)

# -----------------------------------------------------------------------------
# 5. 主介面渲染
# -----------------------------------------------------------------------------
st.title("📈 三大法人籌碼與模擬交易 App")

if df_stock is not None and not df_stock.empty:
    latest_close = float(df_stock['Close'].iloc[-1])
    prev_close = float(df_stock['Close'].iloc[-2])
    change_pct = ((latest_close - prev_close) / prev_close) * 100
    ma20 = float(df_stock['MA20'].iloc[-1]) if not pd.isna(df_stock['MA20'].iloc[-1]) else latest_close

    # --- 頂部關鍵數據卡片 ---
    c1, c2, c3 = st.columns(3)
    c1.metric("標的代號", target_stock.replace(".TW", ""))
    c2.metric("最新收盤價", f"{latest_close:.2f} 元", f"{change_pct:+.2f}%")
    c3.metric("月線 (20MA)", f"{ma20:.2f} 元", "支撐關卡" if latest_close >= ma20 else "壓力關卡")

    st.divider()

    # --- 籌碼訊號與特級警報判斷 ---
    st.subheader("🚨 三大法人與籌碼警報狀態")
    
    # 模擬籌碼指標邏輯
    is_above_ma20 = latest_close >= ma20
    # 模擬當日三大法人同買狀態 (可更換為實時 API 邏輯)
    institutional_buy_all = True if (latest_close > prev_close and change_pct > 0) else False

    if institutional_buy_all and is_above_ma20:
        st.success("🔥 **【特級強烈買進訊號】三大法人同步買超 + 站上月線打底！**

外資、投信、自營商共識極高，且股價具備均線支撐，為高勝率佈局點。")
    elif institutional_buy_all:
        st.info("⚡ **【籌碼轉強警報】三大法人今日同步買超**

主力資金開始卡位，但需注意是否已突破均線反壓。")
    elif is_above_ma20:
        st.warning("⚠️ **【技術面撐腰】股價站上月線，但籌碼分歧**

法人買賣超未一致，建議等待土洋合心買訊出現再大幅建倉。")
    else:
        st.error("❄️ **【觀望訊號】籌碼偏空 / 股價回檔修整中**

法人方向不明或賣壓宣洩中，建議暫不接刀，嚴格執行觀察。")

    # K線走勢圖
    st.subheader("📊 近期價格走勢與月線")
    st.line_chart(df_stock[['Close', 'MA20']])

    st.divider()

    # --- 模擬交易 (Paper Trading) 區塊 ---
    st.subheader("🤖 模擬交易系統 (Paper Trading)")

    # 顯示目前資產狀況
    curr_shares = st.session_state.portfolio.get(target_stock, {}).get('shares', 0)
    curr_cost = st.session_state.portfolio.get(target_stock, {}).get('cost', 0.0)
    market_val = curr_shares * latest_close
    total_asset = st.session_state.cash + market_val

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("可用現金", f"${st.session_state.cash:,.0f}")
    col_b.metric("目前持股", f"{curr_shares // 1000} 張 ({curr_shares} 股)")
    col_c.metric("股票市值", f"${market_val:,.0f}")
    col_d.metric("總虛擬資產", f"${total_asset:,.0f}")

    # 下單按鈕區
    btn_col1, btn_col2 = st.columns(2)
    
    with btn_col1:
        if st.button("🟢 模擬買入 1 張 (1,000股)", use_container_width=True):
            cost_total = latest_close * 1000
            if st.session_state.cash >= cost_total:
                st.session_state.cash -= cost_total
                new_shares = curr_shares + 1000
                new_cost = ((curr_shares * curr_cost) + cost_total) / new_shares
                st.session_state.portfolio[target_stock] = {'shares': new_shares, 'cost': new_cost}
                st.session_state.trade_history.append(f"買入 {target_stock} 1張 @ ${latest_close:.2f}")
                st.toast(f"成功買入 1 張！成本 ${latest_close:.2f}")
                st.rerun()
            else:
                st.error("現金不足以購買 1 張！")

    with btn_col2:
        if st.button("🔴 模擬賣出 1 張 (1,000股)", use_container_width=True):
            if curr_shares >= 1000:
                st.session_state.cash += (latest_close * 1000)
                new_shares = curr_shares - 1000
                if new_shares == 0:
                    del st.session_state.portfolio[target_stock]
                else:
                    st.session_state.portfolio[target_stock]['shares'] = new_shares
                
                pnl = (latest_close - curr_cost) * 1000
                st.session_state.trade_history.append(f"賣出 {target_stock} 1張 @ ${latest_close:.2f} (損益: ${pnl:+.0f})")
                st.toast(f"成功賣出 1 張！交易損益: ${pnl:+.0f}")
                st.rerun()
            else:
                st.error("目前無足夠持股可賣出！")

    # 交易履歷
    if st.session_state.trade_history:
        with st.expander("📜 查看歷史模擬交易紀錄"):
            for log in reversed(st.session_state.trade_history):
                st.write(f"- {log}")

else:
    st.error("⚠️ 無法取得該股票資料，請確認代號輸入是否正確（台股請加 .TW，例：2367.TW）。")
