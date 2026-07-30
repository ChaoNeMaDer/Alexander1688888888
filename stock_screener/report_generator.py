"""
HTML 報表產生器
深色主題 TradingView 風格，含排序與互動功能
"""
import os
from datetime import datetime
import config


def generate_report(results, total_scanned, output_path="report.html"):
    """
    產生精美 HTML 報表。

    Parameters
    ----------
    results : list[dict]  每個 dict 含:
        code, name, market, close, change_pct, volume_lots,
        daily_buy_reason, daily_trend_code, daily_trend_text,
        weekly_reason, weekly_trend_code, weekly_trend_text
    total_scanned : int
    output_path : str
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    count = len(results)

    rows_html = ""
    for i, r in enumerate(results, 1):
        chg = r.get("change_pct", 0)
        chg_color = "#26a69a" if chg >= 0 else "#ef5350"
        chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"

        d_trend_cls = _trend_class(r["daily_trend_code"])
        w_trend_cls = _trend_class(r["weekly_trend_code"])

        tv_link = f"https://www.tradingview.com/chart/?symbol=TWSE%3A{r['code']}"

        rows_html += f"""
        <tr>
          <td>{i}</td>
          <td><a href="{tv_link}" target="_blank" class="stock-link">{r['code']}</a></td>
          <td>{r['name']}</td>
          <td><span class="badge badge-{'twse' if r['market']=='TWSE' else 'tpex'}">{r['market']}</span></td>
          <td style="color:{chg_color};font-weight:600">{r['close']:.2f}</td>
          <td style="color:{chg_color};font-weight:600">{chg_str}</td>
          <td>{r['volume_lots']:,}</td>
          <td><span class="badge badge-buy">{r['daily_buy_reason']}</span></td>
          <td><span class="trend {d_trend_cls}">{r['daily_trend_text']}</span></td>
          <td><span class="badge badge-buy-dim">{r['weekly_reason']}</span></td>
          <td><span class="trend {w_trend_cls}">{r['weekly_trend_text']}</span></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>箱波均選股結果 — {now}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family: 'Inter', sans-serif;
  background: #0f1117;
  color: #e0e0e0;
  min-height: 100vh;
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}

/* Header */
.header {{
  background: linear-gradient(135deg, #1a1e2e 0%, #12141c 100%);
  border: 1px solid rgba(240,185,11,0.15);
  border-radius: 16px;
  padding: 32px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
}}
.header::before {{
  content: '';
  position: absolute;
  top: -50%; right: -10%;
  width: 300px; height: 300px;
  background: radial-gradient(circle, rgba(240,185,11,0.08) 0%, transparent 70%);
  border-radius: 50%;
}}
.header h1 {{
  font-size: 28px;
  font-weight: 700;
  background: linear-gradient(90deg, #f0b90b, #f5d76e);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 8px;
}}
.header .subtitle {{ color: #888; font-size: 14px; }}

/* Stats Cards */
.stats {{
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}}
.stat-card {{
  flex: 1;
  min-width: 180px;
  background: linear-gradient(135deg, #1e222d 0%, #181b25 100%);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  transition: transform 0.2s, box-shadow 0.2s;
}}
.stat-card:hover {{
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}}
.stat-card .value {{
  font-size: 32px;
  font-weight: 700;
  color: #f0b90b;
}}
.stat-card .label {{
  font-size: 13px;
  color: #888;
  margin-top: 4px;
}}

/* Table */
.table-wrapper {{
  background: #1e222d;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.06);
  overflow-x: auto;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}}
th {{
  background: #262a36;
  color: #f0b90b;
  font-weight: 600;
  padding: 14px 12px;
  text-align: left;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
  transition: background 0.2s;
}}
th:hover {{ background: #2d3242; }}
th::after {{
  content: ' ⇅';
  font-size: 11px;
  opacity: 0.4;
}}
td {{
  padding: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  white-space: nowrap;
}}
tr {{ transition: background 0.15s; }}
tr:hover {{ background: rgba(240,185,11,0.04); }}

/* Badges & Tags */
.badge {{
  display: inline-block;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}}
.badge-buy {{
  background: rgba(38,166,154,0.15);
  color: #26a69a;
  border: 1px solid rgba(38,166,154,0.3);
}}
.badge-buy-dim {{
  background: rgba(38,166,154,0.08);
  color: #4db6ac;
  border: 1px solid rgba(38,166,154,0.15);
}}
.badge-twse {{
  background: rgba(30,136,229,0.12);
  color: #42a5f5;
}}
.badge-tpex {{
  background: rgba(171,71,188,0.12);
  color: #ce93d8;
}}
.trend {{ font-size: 13px; font-weight: 500; }}
.trend-bull {{ color: #26a69a; }}
.trend-bear {{ color: #ef5350; }}
.trend-conv {{ color: #ff9800; }}
.trend-neut {{ color: #888; }}

.stock-link {{
  color: #42a5f5;
  text-decoration: none;
  font-weight: 600;
  transition: color 0.2s;
}}
.stock-link:hover {{ color: #90caf9; text-decoration: underline; }}

.no-results {{
  text-align: center;
  padding: 60px 20px;
  color: #666;
  font-size: 18px;
}}

.footer {{
  text-align: center;
  padding: 24px;
  color: #555;
  font-size: 12px;
}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 箱波均戰法 — 選股結果</h1>
    <div class="subtitle">掃描時間：{now}　|　篩選條件：週K已買進 + 日K當日新買進訊號　|　成交量 ≥ {config.MIN_VOLUME_LOTS} 張　|　股價 ≤ {config.MAX_PRICE} 元</div>
  </div>

  <div class="stats">
    <div class="stat-card">
      <div class="value">{total_scanned}</div>
      <div class="label">掃描股票數</div>
    </div>
    <div class="stat-card">
      <div class="value" style="color:#26a69a">{count}</div>
      <div class="label">符合條件</div>
    </div>
    <div class="stat-card">
      <div class="value" style="color:#42a5f5">{sum(1 for r in results if r['market']=='TWSE')}</div>
      <div class="label">上市</div>
    </div>
    <div class="stat-card">
      <div class="value" style="color:#ce93d8">{sum(1 for r in results if r['market']!='TWSE')}</div>
      <div class="label">上櫃</div>
    </div>
  </div>

  <div class="table-wrapper">
    {"<p class='no-results'>🔍 今日無符合條件的股票</p>" if count == 0 else f'''
    <table id="resultTable">
      <thead>
        <tr>
          <th>#</th><th>代碼</th><th>名稱</th><th>市場</th>
          <th>收盤價</th><th>漲跌幅</th><th>成交量(張)</th>
          <th>日K買進原因</th><th>日K均線狀態</th>
          <th>週K買進原因</th><th>週K均線狀態</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>'''}
  </div>

  <div class="footer">
    箱波均戰法選股系統 — 資料來源：TWSE/TPEx OpenAPI + Yahoo Finance<br>
    均線參數：日K {config.DAILY_MA} / 週K {config.WEEKLY_MA}
  </div>
</div>

<script>
document.querySelectorAll('#resultTable th').forEach((th, idx) => {{
  let asc = true;
  th.addEventListener('click', () => {{
    const tbody = document.querySelector('#resultTable tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a, b) => {{
      let av = a.children[idx].textContent.trim();
      let bv = b.children[idx].textContent.trim();
      let an = parseFloat(av.replace(/[^\\d.\\-]/g, ''));
      let bn = parseFloat(bv.replace(/[^\\d.\\-]/g, ''));
      if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach((r, i) => {{
      r.children[0].textContent = i + 1;
      tbody.appendChild(r);
    }});
    asc = !asc;
  }});
}});
</script>
</body>
</html>"""

    abs_path = os.path.abspath(output_path)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(html)
    return abs_path


def _trend_class(code):
    if code in (1, 2):
        return "trend-bull"
    if code in (-1, -2):
        return "trend-bear"
    if code == 3:
        return "trend-conv"
    return "trend-neut"
