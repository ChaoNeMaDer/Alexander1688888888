import streamlit as st
import requests
from streamlit_autorefresh import st_autorefresh

# -----------------------------------------------------------------------------
# 1. 頁面基本設定
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="即時股價",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# -----------------------------------------------------------------------------
# 2. 側邊欄控制面板
# -----------------------------------------------------------------------------
st.sidebar.title("⚙️ 控制面板")
raw_stock_id = st.sidebar.text_input("輸入台股代號", value="2330", help="可輸入上市或上櫃股票代號，例如：2330、0050、6488")
stock_id = ''.join(e for e in raw_stock_id if e.isalnum()).upper() or "2330"

refresh_sec = st.sidebar.selectbox("自動刷新間隔（秒）", [5, 10, 30], index=0)
st.sidebar.button("🔄 立即刷新")

st_autorefresh(interval=refresh_sec * 1000, key="stock_autorefresh")

# -----------------------------------------------------------------------------
# 3. 數據抓取：TWSE MIS 即時行情 API（免金鑰，依序嘗試上市/上櫃）
# -----------------------------------------------------------------------------
def fetch_realtime_quote(stock_code):
    headers = {"User-Agent": "Mozilla/5.0"}
    for ex in ("tse", "otc"):
        try:
            url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex}_{stock_code}.tw&json=1&delay=0"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get("rtcode") == "0000" and data.get("msgArray"):
                    return data["msgArray"][0]
        except Exception:
            pass
    return None


def fmt_price(value):
    try:
        return f"{float(value):.2f} 元"
    except (TypeError, ValueError):
        return "-"


# -----------------------------------------------------------------------------
# 4. 主介面渲染
# -----------------------------------------------------------------------------
st.title("⚡ 即時股價")

quote = fetch_realtime_quote(stock_id)

if quote:
    name = quote.get("n", stock_id)
    prev_close = float(quote.get("y", 0) or 0)
    price_raw = quote.get("z", "-")
    is_live = price_raw not in ("-", "", None)
    price = float(price_raw) if is_live else prev_close

    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    time_str = quote.get("t", "-")

    c1, c2, c3 = st.columns(3)
    c1.metric("股票", f"{name} ({stock_id})")
    c2.metric("成交價", f"{price:.2f} 元", f"{change:+.2f} ({change_pct:+.2f}%)")
    try:
        volume_display = f"{int(quote.get('v', 0)):,} 股"
    except (TypeError, ValueError):
        volume_display = "-"
    c3.metric("成交量", volume_display)

    d1, d2, d3 = st.columns(3)
    d1.metric("開盤", fmt_price(quote.get("o")))
    d2.metric("最高", fmt_price(quote.get("h")))
    d3.metric("最低", fmt_price(quote.get("l")))

    if is_live:
        st.caption(f"🟢 盤中即時資料，資料時間：{time_str}")
    else:
        st.caption(f"⚪ 尚無成交或已收盤，顯示昨收價，資料時間：{time_str}")

    st.caption(f"每 {refresh_sec} 秒自動刷新一次")
else:
    st.error(f"⚠️ 查無股票代號【{stock_id}】的即時報價，請確認輸入無誤。")
