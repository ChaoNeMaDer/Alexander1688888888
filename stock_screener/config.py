# ═══════════════════════════════════════════════
# 箱波均戰法 — 選股參數配置
# 完全對應 boxwave_ma_dw_multi_v2.pine
# ═══════════════════════════════════════════════
import os

# --- 日K 均線設定 ---
DAILY_MA = [5, 20, 60, 120, 240]

# --- 週K 均線設定 ---
WEEKLY_MA = [5, 10, 20, 40, 52]

# --- 次箱 Pivot 長度 ---
PIVOT_LEN_DAILY = 5
PIVOT_LEN_WEEKLY = 5

# --- 缺口幅度 (%) ---
GAP_PCT_DAILY = 0.20
GAP_PCT_WEEKLY = 0.50

# --- 均線糾結判斷 (%) ---
CONVERGE_PCT_DAILY = 0.8
CONVERGE_PCT_WEEKLY = 1.0

# --- 出水芙蓉 Body 佔比 ---
BODY_MIN_PCT = 0.6

# --- 篩選條件 ---
MIN_VOLUME_LOTS = 1000      # 最低成交量（張）
MIN_VOLUME_SHARES = MIN_VOLUME_LOTS * 1000  # 轉換為股數
MAX_PRICE = 500             # 最高股價（元），超過此價格的股票不列入

# --- 三大法人連續買賣超天數（籌碼面確認標籤，非篩選門檻）---
INST_STREAK_TRADING_DAYS = 10  # 回看的交易日數

# --- 資料下載設定 ---
DOWNLOAD_PERIOD = "2y"      # 日K 歷史資料長度（需涵蓋 MA240）
DOWNLOAD_BATCH_SIZE = 30    # 每批下載的股票數量
DOWNLOAD_DELAY = 1.0        # 每批之間的延遲秒數

# --- 報表輸出資料夾 ---
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# --- 均線趨勢代碼對照 ---
TREND_LABELS = {
    1: "📈 多頭排列",
    2: "📈 短多",
    3: "🔀 糾結",
    0: "⏸️ 中性",
    -2: "📉 短空",
    -1: "📉 空頭排列",
}

# --- 買進原因對照 ---
BUY_REASONS = {
    "box": "過而不破",
    "gap": "止跌缺口",
    "lotus": "出水芙蓉",
    "cannon": "多方炮",
}
