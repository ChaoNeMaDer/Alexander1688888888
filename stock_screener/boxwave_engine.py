"""
箱波均戰法核心引擎
忠實翻譯 boxwave_ma_dw_multi_v2.pine 的 calcSignalAndTrend() 函數
"""
import numpy as np
import pandas as pd


def calc_signal_and_trend(df, ma_periods, pivot_len, gap_pct, converge_pct,
                          body_min_pct=0.6):
    """
    完全對應 Pine Script calcSignalAndTrend()。

    Parameters
    ----------
    df : DataFrame  — 必須含 Open, High, Low, Close 欄位
    ma_periods : list[int]  — [p1, p2, p3, p4, p5]
    pivot_len : int
    gap_pct : float
    converge_pct : float
    body_min_pct : float

    Returns
    -------
    dict | None
        last_sig          : int   (1=買, -1=賣, 0=無)
        reason            : str   最後訊號原因
        trend_code        : int   均線趨勢代碼
        is_new_buy_today  : bool  最後一根 K 棒觸發買進
        buy_reason        : str   今日買進原因（若有）
    """
    min_bars = max(ma_periods) + pivot_len * 2 + 10
    if len(df) < min_bars:
        return None

    p1, p2, p3, p4, p5 = ma_periods
    n = len(df)

    # ── 提取 numpy 陣列（避免迴圈中用 pandas）──
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    lo = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)

    # ── SMA ──
    def sma(arr, period):
        s = pd.Series(arr).rolling(period, min_periods=period).mean().values
        return s

    maA = sma(c, p1)
    maB = sma(c, p2)
    maC = sma(c, p3)
    maD = sma(c, p4)

    # ── 多空排列 ──
    _nan = np.isnan
    bullish = np.array([(not _nan(maA[i]) and not _nan(maB[i]) and not _nan(maC[i])
                         and maA[i] > maB[i] and maB[i] > maC[i]) for i in range(n)])
    full_bull = np.array([(bullish[i] and not _nan(maD[i]) and maC[i] > maD[i])
                          for i in range(n)])
    bearish = np.array([(not _nan(maA[i]) and not _nan(maB[i]) and not _nan(maC[i])
                         and maA[i] < maB[i] and maB[i] < maC[i]) for i in range(n)])
    full_bear = np.array([(bearish[i] and not _nan(maD[i]) and maC[i] < maD[i])
                          for i in range(n)])

    # ── 均線糾結 ──
    converge = np.zeros(n, dtype=bool)
    for i in range(n):
        if _nan(maA[i]) or _nan(maB[i]) or _nan(maC[i]):
            continue
        avg = (maA[i] + maB[i] + maC[i]) / 3
        if avg > 0:
            converge[i] = (abs(maA[i] - maC[i]) / avg * 100) < converge_pct

    # ── MA 方向 ──
    maAUp = np.zeros(n, dtype=bool)
    maADn = np.zeros(n, dtype=bool)
    maBUp = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not _nan(maA[i]) and not _nan(maA[i - 1]):
            maAUp[i] = maA[i] > maA[i - 1]
            maADn[i] = maA[i] < maA[i - 1]
        if not _nan(maB[i]) and not _nan(maB[i - 1]):
            maBUp[i] = maB[i] > maB[i - 1]

    # ── 死叉 ──
    deathX = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if (_nan(maA[i]) or _nan(maB[i]) or _nan(maA[i - 1]) or _nan(maB[i - 1])):
            continue
        deathX[i] = (maA[i - 1] >= maB[i - 1]) and (maA[i] < maB[i])

    # ── 缺口偵測 ──
    stopFall = np.zeros(n, dtype=bool)
    stopRise = np.zeros(n, dtype=bool)
    for i in range(1, n):
        th = c[i - 1] * gap_pct / 100
        if lo[i] > h[i - 1] and (lo[i] - h[i - 1]) >= th:
            stopFall[i] = True
        if h[i] < lo[i - 1] and (lo[i - 1] - h[i]) >= th:
            stopRise[i] = True

    # ── K 線型態 ──
    body = np.abs(c - o)
    rng = h - lo
    ratio = np.where(rng > 0, body / rng, 0.0)

    bigBull = (c > o) & (ratio >= body_min_pct)

    lotus = np.zeros(n, dtype=bool)
    for i in range(n):
        if not bigBull[i]:
            continue
        if _nan(maA[i]) or _nan(maB[i]) or _nan(maC[i]):
            continue
        lotus[i] = (o[i] < maA[i] and o[i] < maB[i] and o[i] < maC[i]
                    and c[i] > maA[i] and c[i] > maB[i] and c[i] > maC[i])

    cannon = np.zeros(n, dtype=bool)
    for i in range(2, n):
        g1 = c[i - 2] > o[i - 2]
        red = c[i - 1] < o[i - 1]
        g2 = c[i] > o[i]
        if not (g1 and red and g2):
            continue
        if c[i] <= c[i - 2]:
            continue
        if _nan(maA[i]) or c[i] <= maA[i]:
            continue
        if abs(c[i - 1] - o[i - 1]) >= body[i - 2]:
            continue
        cannon[i] = True

    # ── Pivot 偵測 ──
    pivHi = np.full(n, np.nan)
    pivLo = np.full(n, np.nan)
    for i in range(2 * pivot_len, n):
        ci = i - pivot_len
        win = c[i - 2 * pivot_len: i + 1]
        if _nan(c[ci]):
            continue
        valid = win[~np.isnan(win)]
        if len(valid) == 0:
            continue
        if c[ci] >= np.max(valid):
            pivHi[i] = c[ci]
        if c[ci] <= np.min(valid):
            pivLo[i] = c[ci]

    # ── 逐 bar 狀態機（買賣交替過濾）──
    _ph1 = np.nan; _ph2 = np.nan
    _pl1 = np.nan; _pl2 = np.nan
    _lastSig = 0

    buy_f = np.zeros(n, dtype=bool)
    sell_f = np.zeros(n, dtype=bool)
    sig_arr = np.zeros(n, dtype=int)
    buy_reason = [""] * n
    sell_reason = [""] * n

    for i in range(n):
        if not _nan(pivHi[i]):
            _ph2 = _ph1
            _ph1 = pivHi[i]
        if not _nan(pivLo[i]):
            _pl2 = _pl1
            _pl1 = pivLo[i]

        # ── 買進條件 ──
        aboveBox = (not _nan(_ph1)) and c[i] > _ph1
        holdLow = (not _nan(_pl1)) and (not _nan(_pl2)) and _pl1 >= _pl2
        aUp = bool(maAUp[i])
        cGtA = (not _nan(maA[i])) and c[i] > maA[i]

        bBox = aboveBox and holdLow and aUp and cGtA
        bGap = bool(stopFall[i]) and aUp and bool(maBUp[i])
        bLotus = bool(lotus[i])
        bCannon = bool(cannon[i]) and bool(bullish[i])
        buySig = bBox or bGap or bLotus or bCannon

        # ── 賣出條件 ──
        belowBox = (not _nan(_pl1)) and c[i] < _pl1
        failHigh = (not _nan(_ph1)) and (not _nan(_ph2)) and _ph1 <= _ph2
        aDn = bool(maADn[i])
        cLtA = (not _nan(maA[i])) and c[i] < maA[i]
        cLtC = (not _nan(maC[i])) and c[i] < maC[i]

        sBox = belowBox and failHigh and aDn and cLtA
        sGap = bool(stopRise[i]) and aDn
        sCross = bool(deathX[i]) and cLtC
        sellSig = sBox or sGap or sCross

        # 交替過濾
        bf = buySig and _lastSig != 1
        sf = sellSig and _lastSig != -1
        if bf and sf:
            # 同一根K棒買進、賣出條件同時成立，訊號互相矛盾，兩者都不採信、狀態維持不變
            bf = False
            sf = False
        if bf:
            _lastSig = 1
        if sf:
            _lastSig = -1

        buy_f[i] = bf
        sell_f[i] = sf
        sig_arr[i] = _lastSig

        if bBox:
            buy_reason[i] = "過而不破"
        elif bGap:
            buy_reason[i] = "止跌缺口"
        elif bLotus:
            buy_reason[i] = "出水芙蓉"
        elif bCannon:
            buy_reason[i] = "多方炮"

        if sBox:
            sell_reason[i] = "破而不過"
        elif sGap:
            sell_reason[i] = "止漲缺口"
        elif sCross:
            sell_reason[i] = "死叉破線"

    # ── 最後一根 bar 結果 ──
    last = n - 1
    if full_bull[last]:
        tc = 1
    elif full_bear[last]:
        tc = -1
    elif bullish[last]:
        tc = 2
    elif bearish[last]:
        tc = -2
    elif converge[last]:
        tc = 3
    else:
        tc = 0

    ls = sig_arr[last]
    reason = buy_reason[last] if ls == 1 else sell_reason[last] if ls == -1 else ""

    return {
        "last_sig": ls,
        "reason": reason,
        "trend_code": tc,
        "is_new_buy_today": bool(buy_f[last]),
        "buy_reason": buy_reason[last],
    }
