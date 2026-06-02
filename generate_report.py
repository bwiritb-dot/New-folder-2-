"""generate_report.py — CryptoDatEx BTC Intelligence Report"""

import json, pathlib, datetime, math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.gridspec import GridSpec
import matplotlib.ticker as mticker

matplotlib.rcParams['font.family'] = 'DejaVu Sans'
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['text.parse_math'] = False

# ─── Data loading ─────────────────────────────────────────────────────────────
OUTPUT = pathlib.Path('output')

def load_json(pattern):
    """Find most recently modified file matching pattern, searching recursively."""
    matches = list(OUTPUT.rglob(pattern))
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime)
    with open(matches[-1], encoding='utf-8') as f:
        return json.load(f)

sm       = load_json('summary_metrics_*.json') or []
oi_info  = load_json('oi_info_*.json')
oi_chart = load_json('oi_chart_v3_*.json')
funding  = load_json('funding_rate_history_*.json')
coinbase = load_json('coinbase_premium_*.json')
raw_btc  = load_json('raw_BTC_*.json')

idx = {r['metric_key']: r for r in sm}

def v(key, default='N/A'):
    r = idx.get(key)
    return r['value'] if r and r['value'] not in ('n/a', None) else default

def nv(key, default=0.0):
    r = idx.get(key)
    if r and r['value'] not in ('n/a', None):
        try: return float(r['value'])
        except: pass
    return default

# ─── Key values ───────────────────────────────────────────────────────────────
PRICE      = nv('current_price', 0.0) or 76527.3
DATE_STR   = datetime.datetime.now().strftime('%Y%m%d')

# Dynamic report date from metrics data
_timestamps = [r.get("updated_at", "") for r in sm if r.get("updated_at")]
REPORT_DT   = max(_timestamps) if _timestamps else datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")

# Clusters from top-5 zones
clusters = []
for i in range(1, 6):
    rng  = v(f'top_zone_{i}_range_24h', '')
    vol  = nv(f'top_zone_{i}_vol_24h', 0)
    note = idx.get(f'top_zone_{i}_vol_24h', {}).get('notes', '') if idx.get(f'top_zone_{i}_vol_24h') else ''
    if not rng or not vol: continue
    side = 'above' if 'above' in note else 'below'
    try:
        dist_parts = note.split('| ')
        dist = float(dist_parts[1].split('%')[0]) if len(dist_parts) > 1 else 0.0
    except: dist = 0.0
    try:
        lo_s, hi_s = rng.replace('$','').replace(',','').split('-')
        lo, hi = float(lo_s), float(hi_s)
    except: lo = hi = PRICE
    clusters.append({'rank':i,'lo':lo,'hi':hi,'center':(lo+hi)/2,
                     'vol':vol,'side':side,'dist':dist})

above_clusters = sorted([c for c in clusters if c['side']=='above'], key=lambda x: x['dist'])
below_clusters = sorted([c for c in clusters if c['side']=='below'], key=lambda x: x['dist'])

# ─── Computed scores ──────────────────────────────────────────────────────────
imb_1   = nv('bucket_1.0%_imbalance_24h', 1.0)
fund_z  = nv('funding_zscore', 0.0)
oi_d24  = nv('oi_delta_24h', 0.0)
oi_d7d  = nv('oi_delta_7d', 0.0)

vol_score = round(min(
    min(abs(math.log(max(imb_1, 0.01))), 3) * 2.0 +
    min(abs(fund_z), 3) * 0.8 +
    (1.5 if nv('nearest_below_dist_24h', 1.0) < 0.5 else 0.5),
10), 1)

dir_bias = 0.0
if imb_1 > 1: dir_bias += min((imb_1 - 1) * 0.8, 3.0)
else:         dir_bias -= min((1 - imb_1) * 0.8, 3.0)
if fund_z < -1.5: dir_bias += min(abs(fund_z + 1.5) * 0.5, 1.5)
elif fund_z > 1.5: dir_bias -= min((fund_z - 1.5) * 0.5, 1.5)
if oi_d24 < 0: dir_bias -= 0.3
dir_bias = round(max(-5.0, min(5.0, dir_bias)), 1)

liq_state = v('liquidation_state', 'neutral')
liq_bias  = v('liquidation_direction_bias', 'balanced')

# ─── Derived analytical values ────────────────────────────────────────────────
nb = nv('nearest_below_price_24h', PRICE * 0.98)
na = nv('nearest_above_price_24h', PRICE * 1.02)
try:
    nb = float(str(nb).replace('$','').replace(',',''))
except: nb = PRICE * 0.98
try:
    na = float(str(na).replace('$','').replace(',',''))
except: na = PRICE * 1.02

na_vol_b     = nv('nearest_above_vol_24h', 0) / 1e9
nb_vol_b     = nv('nearest_below_vol_24h', 0) / 1e9
na_dist      = nv('nearest_above_dist_24h', (na - PRICE) / PRICE * 100 if PRICE else 0)
nb_dist      = nv('nearest_below_dist_24h', (PRICE - nb) / PRICE * 100 if PRICE else 0)

z1_range     = v('top_zone_1_range_24h', 'N/A')
z1_vol_b     = nv('top_zone_1_vol_24h', 0) / 1e9
z1_note      = idx.get('top_zone_1_vol_24h', {}).get('notes', '') if idx.get('top_zone_1_vol_24h') else ''

cb_prem      = nv('coinbase_premium_current', 0.0)
cb_state     = v('coinbase_premium_state', 'neutral')
fund_cur     = nv('funding_current', 0.0)
fund_state   = v('funding_state', 'neutral')
fund_daily   = abs(fund_cur) * 3  # 3 funding periods / day
fund_side    = 'Shorts' if fund_cur < 0 else 'Longs'

oi_trend     = 'declining' if oi_d24 < 0 else 'rising'
oi_action    = 'de-leveraging' if oi_d24 < 0 else 'accumulating leverage'

# Vacuum gap from metrics notes
vac_notes    = idx.get('liquidity_vacuum_24h', {}).get('notes', '') if idx.get('liquidity_vacuum_24h') else ''
if '|' in vac_notes:
    vac_range = vac_notes.split('|')[0].strip()
    vac_pct_str = vac_notes.split('|')[1].replace(' of price','').strip()
else:
    vac_range = 'N/A'; vac_pct_str = 'N/A'

# Targets from cluster data
ext_target_str = 'N/A'
if len(above_clusters) > 1:
    ac2 = above_clusters[1]
    ext_target_str = f"${ac2['center']:,.0f} (Zone, +{ac2['dist']:.2f}%)"

crowd_stop_str = 'N/A'
deep_stop_str  = 'N/A'
support_str    = 'N/A'
if below_clusters:
    bc1 = below_clusters[0]
    crowd_stop_str = f"${bc1['lo']:,.0f}-${bc1['hi']:,.0f} (${bc1['vol']/1e9:.1f}B)"
    support_str    = crowd_stop_str
if len(below_clusters) > 1:
    bc2 = below_clusters[1]
    deep_stop_str = f"${bc2['center']:,.0f} -> ${bc2['lo']:,.0f}"

# Squeeze direction
squeeze_side   = 'SHORT' if liq_bias == 'short_pressure' else 'LONG' if liq_bias == 'long_pressure' else 'NEUTRAL'
squeeze_dir    = 'UPWARD' if squeeze_side == 'SHORT' else 'DOWNWARD' if squeeze_side == 'LONG' else 'N/A'
liq_cascade    = f"short" if squeeze_side == 'SHORT' else 'long'

# Probability matrix
bull_pct  = max(15, min(65, 35 + round(dir_bias * 5)))
bear_pct  = max(15, min(55, 35 - round(dir_bias * 5)))
range_pct = max(10, 100 - bull_pct - bear_pct)

bull_target_str = f"${na:,.0f}"
if len(above_clusters) > 1:
    bull_target_str += f" -> ${above_clusters[1]['center']:,.0f}"
bear_target_str = f"${nb:,.0f}"
if len(below_clusters) > 1:
    bear_target_str += f" -> ${below_clusters[1]['center']:,.0f}"

range_lo = min(nb, PRICE * 0.98)
range_hi = max(na, PRICE * 1.02)

# Smart summary of conditions
cond_squeeze = (abs(imb_1 - 1) > 0.3)
cond_extreme = (abs(imb_1 - 1) > 1.0)
imb_direction = 'ABOVE' if imb_1 > 1 else 'BELOW'
imb_label = 'EXTREME' if cond_extreme else 'ELEVATED' if cond_squeeze else 'BALANCED'

# ─── Theme ────────────────────────────────────────────────────────────────────
BG      = '#0d1117'
GREEN   = '#1db954'
RED     = '#e74c3c'
YELLOW  = '#f39c12'
BLUE    = '#3498db'
WHITE   = '#e6edf3'
GRAY    = '#8b949e'
DARK_BG = '#161b22'
BORDER  = '#30363d'

def style_ax(ax, title='', xlabel='', ylabel=''):
    ax.set_facecolor(DARK_BG)
    ax.tick_params(colors=WHITE, labelsize=8)
    for sp in ax.spines.values(): sp.set_edgecolor(BORDER)
    if title:  ax.set_title(title, color=WHITE, fontsize=9, pad=5, fontweight='bold')
    if xlabel: ax.set_xlabel(xlabel, color=GRAY, fontsize=8)
    if ylabel: ax.set_ylabel(ylabel, color=GRAY, fontsize=8)
    ax.grid(True, color=BORDER, linewidth=0.4, alpha=0.6)

def prob_pct(c):
    d = max(c['dist'], 0.01)
    return round(min(95, max(5, (1/d)*8 + c['vol']/50e9*30)))

# ═══════════════════════════════════════════════════════════════════════════════
output_path = OUTPUT / f'btc_intelligence_{DATE_STR}_onchain.pdf'
print(f'Generating {output_path} ...')
print(f'  Price: ${PRICE:,.2f}  |  Data: {REPORT_DT}')
print(f'  Clusters found: {len(clusters)} (above={len(above_clusters)}, below={len(below_clusters)})')

with PdfPages(str(output_path)) as pdf:

    # ── PAGE 1: Title + Key Metrics + Top-5 table ────────────────────────────
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=BG)
    fig.text(0.5, 0.955, 'CryptoDatEx — BTC On-Chain & Liquidation Intelligence',
             ha='center', color=WHITE, fontsize=17, fontweight='bold')
    fig.text(0.5, 0.918, f'Report: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")}  |  '
             f'Data captured: {REPORT_DT}  |  Instrument: BTC Perpetual Futures',
             ha='center', color=GRAY, fontsize=9.5)

    # KPI strip
    ax_kpi = fig.add_axes([0.04, 0.77, 0.92, 0.125])
    ax_kpi.set_facecolor(DARK_BG); ax_kpi.set_xticks([]); ax_kpi.set_yticks([])
    for sp in ax_kpi.spines.values(): sp.set_edgecolor('#1B7A5A'); sp.set_linewidth(1.8)

    kpis = [
        ('BTC Price',       f'${PRICE:,.0f}',                                          WHITE),
        ('OI Total',        f'${nv("oi_total_current")/1e9:.2f}B',                     BLUE),
        ('OI D24h',         f'{oi_d24:+.2f}%',                                         GREEN if oi_d24>0 else RED),
        ('Funding (8h)',    f'{fund_cur:+.4f}%',                                        GREEN if fund_cur<0 else RED),
        ('Funding State',   fund_state.replace('_',' '),                                GREEN if fund_cur<0 else RED),
        ('F. Z-Score',      f'{fund_z:+.2f}s',                                          GREEN if fund_z<0 else RED),
        ('1% Imbalance',    f'{imb_1:.2f}x',                                            YELLOW),
        ('Liq Bias',        liq_bias.replace('_',' '),                                  YELLOW),
        ('CB Premium',      f'${cb_prem:+.2f}',                                         GREEN if cb_prem>0 else RED),
        ('Vol Score',       f'{vol_score}/10',                                           YELLOW),
        ('Dir Bias',        f'{dir_bias:+.1f}/+/-5',                                    GREEN if dir_bias>0 else RED),
        ('Liq State',       liq_state.replace('_',' '),                                 YELLOW),
    ]
    for i, (lbl, val, col) in enumerate(kpis):
        col_i = i % 6; row_i = i // 6
        x = 0.02 + col_i * 0.165; y = 0.72 - row_i * 0.38
        ax_kpi.text(x, y,      lbl, transform=ax_kpi.transAxes, color=GRAY, fontsize=7.5, va='center')
        ax_kpi.text(x, y-0.28, val, transform=ax_kpi.transAxes, color=col,  fontsize=11,  va='center', fontweight='bold')

    fig.text(0.5, 0.745, f'SIGNAL: {liq_bias.replace("_"," ").upper()}  |  '
             f'Volatility Score: {vol_score}/10  |  Direction Bias: {dir_bias:+.1f}',
             ha='center', color=YELLOW, fontsize=12, fontweight='bold')

    # Top-5 table
    ax_t = fig.add_axes([0.04, 0.08, 0.92, 0.63])
    ax_t.set_facecolor(DARK_BG); ax_t.set_xticks([]); ax_t.set_yticks([])
    for sp in ax_t.spines.values(): sp.set_edgecolor(BORDER)
    ax_t.text(0.5, 0.97, 'TOP-5 LIQUIDATION ZONES (24h Heatmap)', transform=ax_t.transAxes,
              ha='center', color=WHITE, fontsize=10, fontweight='bold')

    hdrs = ['Zone','Price Range','Volume ($B)','Side','Dist %','Type','Test Prob.']
    xs   = [0.01, 0.08, 0.27, 0.39, 0.50, 0.61, 0.84]
    for j, h in enumerate(hdrs):
        ax_t.text(xs[j], 0.89, h, transform=ax_t.transAxes, color=GRAY, fontsize=8, fontweight='bold')
    for i, c in enumerate(clusters):
        y = 0.76 - i*0.155
        col = GREEN if c['side']=='above' else RED
        liq_type = 'Short Liq (squeeze UP)' if c['side']=='above' else 'Long Liq (squeeze DOWN)'
        vals = [f"#{c['rank']}", f"${c['lo']/1e3:.0f}K-${c['hi']/1e3:.0f}K",
                f"{c['vol']/1e9:.2f}B", c['side'].upper(), f"{c['dist']:.2f}%",
                liq_type, f"{prob_pct(c)}%"]
        for j, val in enumerate(vals):
            vc = col if j in (1,3,5) else WHITE
            ax_t.text(xs[j], y, val, transform=ax_t.transAxes, color=vc, fontsize=8.5)

    lm_price = v('liquidity_magnet_24h', f'${na:,.0f}')
    ax_t.text(0.5, 0.02,
              f'Liquidity Magnet: {lm_price} (+{na_dist:.2f}%, ${na_vol_b:.1f}B)  |  '
              f'Vacuum gap: {vac_range} ({vac_pct_str})  |  '
              f'Clusters: {v("cluster_count_24h")}  |  Total heatmap vol: ${nv("total_volume_24h")/1e9:.1f}B',
              transform=ax_t.transAxes, ha='center', color=GRAY, fontsize=8)

    pdf.savefig(fig, bbox_inches='tight'); plt.close(fig)
    print('  Page 1 done')

    # ── PAGE 2: Chart 1 — Heatmap cluster bar chart ──────────────────────────
    fig, ax = plt.subplots(figsize=(11.69, 8.27), facecolor=BG)
    fig.patch.set_facecolor(BG)

    pv = {}
    if raw_btc:
        inner     = raw_btc.get('data') or raw_btc
        y_lvls    = inner.get('y') or []
        pr_rows   = inner.get('prices') or []
        liq_rows  = inner.get('liq') or []
        for row in liq_rows:
            if len(row) >= 3:
                ti, pi, vol = int(row[0]), int(row[1]), float(row[2])
                if 0 <= ti < len(pr_rows) and 0 <= pi < len(y_lvls):
                    p = float(y_lvls[pi]); pv[p] = pv.get(p,0) + vol

    if pv:
        ps  = sorted(pv); vols = [pv[p] for p in ps]
        gap = (ps[-1]-ps[0])/len(ps)*0.75
        bar_colors = [GREEN if p >= PRICE else RED for p in ps]
        ax.barh(ps, [v2/1e9 for v2 in vols], height=gap, color=bar_colors, alpha=0.75, linewidth=0)

    for c in clusters:
        col = GREEN if c['side']=='above' else RED
        ax.axhspan(c['lo'], c['hi'], alpha=0.18, color=col)
        if pv:
            xmax = max(pv.values())/1e9
            ax.text(xmax*0.98, c['center'],
                    f"  #{c['rank']} ${c['vol']/1e9:.1f}B | {c['dist']:.1f}%",
                    va='center', ha='right', color=col, fontsize=8, fontweight='bold')

    ax.axhline(PRICE, color=YELLOW, linewidth=2.5, linestyle='--', zorder=10)
    if pv:
        ax.text(max(pv.values())/1e9*0.02, PRICE+80, f'BTC ${PRICE:,.0f}',
                color=YELLOW, fontsize=9, fontweight='bold')

    style_ax(ax, 'LIQUIDATION HEATMAP — BTC (24h, 5min intervals, Binance Perpetual)',
             'Liquidation Volume ($B)', 'BTC Price ($)')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f'${x:,.0f}'))

    legend_el = [
        mpatches.Patch(color=GREEN, alpha=0.7, label='Short Liquidations (above price — squeeze UP fuel)'),
        mpatches.Patch(color=RED,   alpha=0.7, label='Long Liquidations (below price — squeeze DOWN fuel)'),
        plt.Line2D([0],[0], color=YELLOW, lw=2.5, ls='--', label=f'Current Price: ${PRICE:,.0f}'),
    ]
    ax.legend(handles=legend_el, loc='lower right',
              facecolor=DARK_BG, edgecolor=BORDER, labelcolor=WHITE, fontsize=9)
    fig.text(0.5, 0.01,
             f'Source: CoinGlass liqHeatMap (AES-ECB decryption)  |  Data: {REPORT_DT}',
             ha='center', color=GRAY, fontsize=8)

    pdf.savefig(fig, bbox_inches='tight'); plt.close(fig)
    print('  Page 2 done')

    # ── PAGE 3: Chart 2 — Price line + zone bands (24h candles) ─────────────
    fig, ax = plt.subplots(figsize=(11.69, 8.27), facecolor=BG)
    fig.patch.set_facecolor(BG)

    candle_ts, candle_c = [], []
    if raw_btc:
        inner = raw_btc.get('data') or raw_btc
        for row in (inner.get('prices') or []):
            if isinstance(row, list) and len(row) >= 5:
                candle_ts.append(int(row[0])); candle_c.append(float(row[4]))

    if candle_c:
        x = list(range(len(candle_c)))
        ax.plot(x, candle_c, color=BLUE, linewidth=1.2, zorder=5)
        ax.fill_between(x, min(candle_c)*0.997, candle_c, color=BLUE, alpha=0.08)

    for c in clusters:
        col = GREEN if c['side']=='above' else RED
        alpha = max(0.08, min(0.25, c['vol']/80e9))
        ax.axhspan(c['lo'], c['hi'], color=col, alpha=alpha, zorder=2)
        nx = len(candle_c)-1 if candle_c else 200
        ax.text(nx*0.97, c['center'], f" #{c['rank']} ${c['vol']/1e9:.1f}B",
                color=col, fontsize=8, fontweight='bold', va='center', ha='right', zorder=6)

    ax.axhline(PRICE, color=YELLOW, linewidth=2, linestyle='--', zorder=8)
    ax.axhline(nb, color=RED,   linewidth=1.2, linestyle=':', alpha=0.9, zorder=7)
    ax.axhline(na, color=GREEN, linewidth=1.2, linestyle=':', alpha=0.9, zorder=7)

    if candle_c:
        mid = len(candle_c)//2
        ax.text(mid, na+80, f'Nearest Short Liq: ${na:,.0f} (+{na_dist:.2f}%)', color=GREEN, fontsize=8)
        ax.text(mid, nb-150, f'Nearest Long Liq: ${nb:,.0f} (-{nb_dist:.2f}%)',  color=RED,   fontsize=8)
        ax.text(mid, PRICE+50, f'Current: ${PRICE:,.0f}', color=YELLOW, fontsize=8, fontweight='bold')

    style_ax(ax, 'BTC PRICE + LIQUIDATION ZONES — 24h (5min candles)',
             'Time (older -> newer)', 'BTC Price ($)')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f'${x:,.0f}'))

    if candle_ts:
        n = len(candle_ts)
        tpos = [int(i*n/6) for i in range(7)]
        ax.set_xticks(tpos)
        ax.set_xticklabels(
            [datetime.datetime.utcfromtimestamp(candle_ts[min(p,n-1)]/1000).strftime('%H:%M')
             for p in tpos], color=GRAY, fontsize=8)

    legend_el = [
        mpatches.Patch(color=GREEN, alpha=0.4, label='Short Liq Zones (squeeze UP)'),
        mpatches.Patch(color=RED,   alpha=0.4, label='Long Liq Zones  (squeeze DOWN)'),
        plt.Line2D([0],[0], color=YELLOW, lw=2,  ls='--', label=f'Price: ${PRICE:,.0f}'),
        plt.Line2D([0],[0], color=GREEN,  lw=1.2,ls=':',  label=f'Nearest Short: ${na:,.0f}'),
        plt.Line2D([0],[0], color=RED,    lw=1.2,ls=':',  label=f'Nearest Long:  ${nb:,.0f}'),
    ]
    ax.legend(handles=legend_el, loc='upper left',
              facecolor=DARK_BG, edgecolor=BORDER, labelcolor=WHITE, fontsize=8.5)
    pdf.savefig(fig, bbox_inches='tight'); plt.close(fig)
    print('  Page 3 done')

    # ── PAGE 4: Chart 3 — Derivatives Dashboard ──────────────────────────────
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=BG)
    fig.patch.set_facecolor(BG)
    fig.suptitle('DERIVATIVES DASHBOARD', color=WHITE, fontsize=13, fontweight='bold', y=0.97)
    gs = GridSpec(2, 3, figure=fig, hspace=0.42, wspace=0.33,
                  left=0.07, right=0.97, top=0.91, bottom=0.08)

    # A — OI over time
    ax_oi = fig.add_subplot(gs[0, 0:2])
    if oi_chart:
        dl = oi_chart.get('dateList') or []
        dm = oi_chart.get('dataMap')  or {}
        totals = []
        for i in range(len(dl)):
            vals = [vv[i] for vv in dm.values() if isinstance(vv,list) and i < len(vv) and vv[i]]
            totals.append(sum(vals)/1e9 if vals else 0)
        n_pts = min(len(totals), 120)
        ot = totals[-n_pts:]; xx = list(range(len(ot)))
        if ot:
            ax_oi.fill_between(xx, ot, color=BLUE, alpha=0.25)
            ax_oi.plot(xx, ot, color=BLUE, linewidth=1.5)
            ax_oi.axhline(ot[-1], color=YELLOW, linewidth=1, linestyle='--', alpha=0.7)
    style_ax(ax_oi,
             f'Open Interest  |  Current: ${nv("oi_total_current")/1e9:.2f}B  D24h: {oi_d24:+.2f}%  D7d: {oi_d7d:+.2f}%',
             '', 'OI ($B)')

    # B — Funding rate bars
    ax_f = fig.add_subplot(gs[0, 2])
    if funding:
        dm2 = funding.get('dataMap') or {}
        dl2 = funding.get('dateList') or []
        agg = []
        for i in range(len(dl2)):
            vals = [vv[i]*100 for vv in dm2.values()
                    if isinstance(vv,list) and i < len(vv) and vv[i] is not None]
            agg.append(sum(vals)/len(vals) if vals else None)
        valid = [(i,a) for i,a in enumerate(agg) if a is not None]
        n_pts = min(len(valid), 42)
        if valid:
            fr = [x[1] for x in valid[-n_pts:]]
            fc = [RED if f<0 else GREEN for f in fr]
            ax_f.bar(range(len(fr)), fr, color=fc, alpha=0.8, width=0.9)
            ax_f.axhline(0, color=WHITE, linewidth=0.8, alpha=0.5)
    style_ax(ax_f,
             f'Funding Rate (8h)\n{fund_cur:+.4f}%  Z={fund_z:+.2f}',
             '', 'Funding %')

    # C — OI by exchange
    ax_ex = fig.add_subplot(gs[1, 0])
    ex_data = [(e, nv(f'oi_{e.lower()}',0), nv(f'oi_{e.lower()}_24h_chg',0))
               for e in ['Binance','CME','Bybit','OKX']]
    ex_data = [x for x in ex_data if x[1]>0]
    if ex_data:
        names  = [x[0] for x in ex_data]
        vals_b = [x[1]/1e9 for x in ex_data]
        chgs   = [x[2] for x in ex_data]
        bc     = [GREEN if c>0 else RED for c in chgs]
        bars   = ax_ex.bar(names, vals_b, color=bc, alpha=0.8)
        for bar, chg in zip(bars, chgs):
            ax_ex.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.04,
                       f'{chg:+.1f}%', ha='center', color=WHITE, fontsize=7.5, fontweight='bold')
    style_ax(ax_ex, 'OI by Exchange ($B)', '', '$B')

    # D — Coinbase premium
    ax_cb = fig.add_subplot(gs[1, 1])
    if isinstance(coinbase, list) and coinbase:
        n_pts = min(len(coinbase), 48)
        cb_c  = [float(r[4]) for r in coinbase[-n_pts:]
                 if isinstance(r,list) and len(r)>=5]
        if cb_c:
            cbc = [GREEN if c>0 else RED for c in cb_c]
            ax_cb.bar(range(len(cb_c)), cb_c, color=cbc, alpha=0.8, width=0.9)
            ax_cb.axhline(0, color=WHITE, linewidth=0.8, alpha=0.5)
    style_ax(ax_cb,
             f'Coinbase Premium (USD)\nCurrent: ${cb_prem:+.2f}  State: {cb_state}',
             '', '$')

    # E — Bucket imbalances
    ax_bk = fig.add_subplot(gs[1, 2])
    bpcts = [0.5, 1.0, 2.0, 3.0, 5.0]
    av = [nv(f'bucket_{p:.1f}%_above_24h',0)/1e9 for p in bpcts]
    bv = [nv(f'bucket_{p:.1f}%_below_24h',0)/1e9 for p in bpcts]
    x  = np.arange(len(bpcts)); w=0.35
    ax_bk.bar(x-w/2, av, w, color=GREEN, alpha=0.8, label='Above (short liq)')
    ax_bk.bar(x+w/2, bv, w, color=RED,   alpha=0.8, label='Below (long liq)')
    ax_bk.set_xticks(x)
    ax_bk.set_xticklabels([f'+-{p}%' for p in bpcts], color=GRAY, fontsize=8)
    ax_bk.legend(fontsize=7, facecolor=DARK_BG, edgecolor=BORDER, labelcolor=WHITE)
    style_ax(ax_bk, 'Liquidation Buckets ($B)', '', '$B')

    pdf.savefig(fig, bbox_inches='tight'); plt.close(fig)
    print('  Page 4 done')

    # ── PAGE 5: 9-Layer Module + Probability Matrix ──────────────────────────
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=BG)
    fig.patch.set_facecolor(BG)

    def text_panel(ax, lines, dy=0.025):
        for i, (txt, col, bold, fs) in enumerate(lines):
            ax.text(0.02, 0.98 - i*dy, txt, transform=ax.transAxes,
                    color=col, fontsize=fs, fontweight='bold' if bold else 'normal', va='top')

    def make_ax(rect, border=BORDER, bw=1):
        a = fig.add_axes(rect); a.set_facecolor(DARK_BG)
        a.set_xticks([]); a.set_yticks([])
        for sp in a.spines.values(): sp.set_edgecolor(border); sp.set_linewidth(bw)
        return a

    ax_L = make_ax([0.02, 0.02, 0.47, 0.96])
    layers = [
        ('LIQUIDATION MODULE — 9 LAYERS', WHITE, True, 9.5),
        ('', GRAY, False, 8),
        ('LAYER 1 — Actual Liquidations', YELLOW, True, 8.5),
        ('  long_liq_Xm / short_liq_Xm: [N/A]', GRAY, False, 8),
        ('  Requires separate liqHistory endpoint', GRAY, False, 8),
        ('', GRAY, False, 8),
        ('LAYER 2 — Heatmap Zones (24h)', YELLOW, True, 8.5),
        (f'  0.5% above: ${nv("bucket_0.5%_above_24h")/1e9:.2f}B  below: ${nv("bucket_0.5%_below_24h")/1e9:.2f}B', GREEN, False, 8),
        (f'  1.0% above: ${nv("bucket_1.0%_above_24h")/1e9:.2f}B  below: ${nv("bucket_1.0%_below_24h")/1e9:.2f}B', GREEN, False, 8),
        (f'  2.0% above: ${nv("bucket_2.0%_above_24h")/1e9:.2f}B  below: ${nv("bucket_2.0%_below_24h")/1e9:.2f}B', GREEN, False, 8),
        (f'  3.0% above: ${nv("bucket_3.0%_above_24h")/1e9:.2f}B  below: ${nv("bucket_3.0%_below_24h")/1e9:.2f}B', GREEN, False, 8),
        (f'  5.0% above: ${nv("bucket_5.0%_above_24h")/1e9:.2f}B  below: ${nv("bucket_5.0%_below_24h")/1e9:.2f}B', GREEN, False, 8),
        ('', GRAY, False, 8),
        ('LAYER 3 — Nearest Clusters', YELLOW, True, 8.5),
        (f'  Nearest SHORT liq: ${na:,.0f} +{na_dist:.2f}%  << LIQUIDITY MAGNET', GREEN, True, 8),
        (f'  Size: ${na_vol_b:.2f}B', GREEN, True, 8),
        (f'  Nearest LONG liq:  ${nb:,.0f} -{nb_dist:.2f}%', RED, False, 8),
        (f'  Size: ${nb_vol_b:.2f}B', RED, False, 8),
        (f'  Largest cluster: {z1_range} (Zone 1, ${z1_vol_b:.1f}B)', YELLOW, True, 8),
        ('', GRAY, False, 8),
        ('LAYER 4 — Imbalance', YELLOW, True, 8.5),
        (f'  1% ratio: {nv("bucket_1.0%_imbalance_24h"):.2f}x  3%: {nv("bucket_3.0%_imbalance_24h"):.2f}x  5%: {nv("bucket_5.0%_imbalance_24h"):.2f}x', WHITE, False, 8),
        (f'  {imb_1:.2f}x at 1% -> {imb_label} {imb_direction} pressure', YELLOW, True, 8),
        ('', GRAY, False, 8),
        ('LAYER 5 — Accumulation Speed', YELLOW, True, 8.5),
        ('  [N/A] — needs 2 heatmap snapshots (add cron)', GRAY, False, 8),
        ('', GRAY, False, 8),
        ('LAYER 6 — OI Context', YELLOW, True, 8.5),
        (f'  OI: ${nv("oi_total_current")/1e9:.2f}B  D24h: {oi_d24:+.2f}%  D7d: {oi_d7d:+.2f}%', BLUE, False, 8),
        (f'  OI {oi_trend}: leverage {"exiting" if oi_d24<0 else "building"}, cascade risk {"falls" if oi_d24<0 else "rises"}', GRAY, False, 8),
        ('', GRAY, False, 8),
        ('LAYER 7 — Funding Context', YELLOW, True, 8.5),
        (f'  Current: {fund_cur:+.5f}% (8h)', RED if fund_z > 0 else GREEN, True, 8),
        (f'  24h avg: {nv("funding_avg_24h"):+.5f}%  7d avg: {nv("funding_avg_7d"):+.5f}%', GRAY, False, 8),
        (f'  Z-Score: {fund_z:+.3f}  State: {fund_state}', RED if fund_z > 1 else GREEN if fund_z < -1 else GRAY, True, 8),
        (f'  {"Negative funding = shorts overloaded, squeeze pressure UPWARD" if fund_cur < -0.0002 else "Positive funding = longs overloaded, squeeze pressure DOWNWARD" if fund_cur > 0.0002 else "Funding neutral"}', YELLOW if abs(fund_z) > 1.5 else GRAY, True, 8),
        ('', GRAY, False, 8),
        ('LAYER 8 — CVD / Taker Flow', YELLOW, True, 8.5),
        ('  [N/A] — needs WebSocket feed', GRAY, False, 8),
        ('', GRAY, False, 8),
        ('LAYER 9 — VWAP / Key Levels', YELLOW, True, 8.5),
        ('  [N/A] — needs VWAP computation', GRAY, False, 8),
    ]
    text_panel(ax_L, layers, dy=0.026)

    ax_R = make_ax([0.53, 0.02, 0.45, 0.96], border='#1B7A5A', bw=2)

    bull_conf = 'Funding(-) + imbalance above + CB Prem(+)' if fund_cur < 0 and imb_1 > 1 else \
                'Funding(-) + imbalance above' if fund_cur < 0 else \
                'CB Premium positive + OI rising' if cb_prem > 0 else 'No strong confirmation'
    bear_conf = 'Funding(+) + imbalance below + CB Prem(-)' if fund_cur > 0 and imb_1 < 1 else \
                'Funding(+) + OI rising + CB Prem(-)' if fund_cur > 0 and cb_prem < 0 else \
                'CB Premium negative + OI declining' if cb_prem < 0 else 'No strong confirmation'

    right = [
        ('FINAL MODULE OUTPUTS', WHITE, True, 9.5),
        ('', GRAY, False, 8),
        (f'liquidation_volatility_score:  {vol_score} / 10', YELLOW, True, 9),
        (f'liquidation_direction_bias:    {dir_bias:+.1f} / +-5', GREEN if dir_bias>0 else RED, True, 9),
        (f'liquidation_state:             {liq_state}', YELLOW, True, 9),
        ('', GRAY, False, 8),
        ('─' * 45, BORDER, False, 8),
        ('PROBABILITY MATRIX (24-72h)', WHITE, True, 9),
        ('', GRAY, False, 8),
        (f'BULLISH — {squeeze_side} Squeeze {squeeze_dir}:  {bull_pct}%', GREEN, True, 9),
        (f'  Target: {bull_target_str}', GREEN, False, 8),
        (f'  Trigger: break ${na:,.0f} with volume', GREEN, False, 8),
        (f'  Conf: {bull_conf}', GREEN, False, 8),
        ('', GRAY, False, 8),
        (f'BEARISH — Long Squeeze DOWN:    {bear_pct}%', RED, True, 9),
        (f'  Target: {bear_target_str}', RED, False, 8),
        (f'  Trigger: break ${nb:,.0f} support cluster', RED, False, 8),
        (f'  Conf: {bear_conf}', RED, False, 8),
        ('', GRAY, False, 8),
        (f'SIDEWAYS — Range:               {range_pct}%', YELLOW, True, 9),
        (f'  Range: ${range_lo:,.0f} - ${range_hi:,.0f}', YELLOW, False, 8),
        ('  Cond: no catalyst, bilateral vol absorbs', YELLOW, False, 8),
        ('', GRAY, False, 8),
        ('─' * 45, BORDER, False, 8),
        ('MICROSTRUCTURE SIGNALS', WHITE, True, 9),
        ('', GRAY, False, 8),
        (f'Liquidity Magnet:   ${na:,.0f} (+{na_dist:.2f}%)', GREEN, True, 8.5),
        (f'  ${na_vol_b:.1f}B short liq — strongest cluster above', GREEN, False, 8),
        (f'Dominant Side:      {squeeze_side} LIQ {"above" if imb_1>1 else "below"}', YELLOW, True, 8.5),
        ('Orderbook Imbal.:   [N/A]', GRAY, False, 8),
        (f'Funding Divergence: {fund_state} (Z={fund_z:+.2f})', RED if abs(fund_z)>1.5 else GRAY, False, 8),
        (f'OI Delta Signal:    OI {oi_trend} -> {"de-leverage" if oi_d24<0 else "accumulation"}', GRAY, False, 8),
        ('', GRAY, False, 8),
        ('─' * 45, BORDER, False, 8),
        ('ON-CHAIN HEALTH SCORE: [N/A]', GRAY, True, 9),
        ('SOPR/NUPL/MVRV/Reserves/LTH/Whales:', GRAY, False, 8),
        ('ETF Flows/Miners: Phase 2 required', GRAY, False, 8),
        ('(Glassnode / CryptoQuant not connected)', GRAY, False, 8),
    ]
    text_panel(ax_R, right, dy=0.024)

    pdf.savefig(fig, bbox_inches='tight'); plt.close(fig)
    print('  Page 5 done')

    # ── PAGE 6: Analyst Conclusion ────────────────────────────────────────────
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=BG)
    fig.patch.set_facecolor(BG)
    fig.text(0.5, 0.965, 'ANALYST CONCLUSION — CryptoDatEx BTC Intelligence',
             ha='center', color=WHITE, fontsize=14, fontweight='bold')
    fig.text(0.5, 0.935, f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")}  |  Data: {REPORT_DT}  |  Language: EN',
             ha='center', color=GRAY, fontsize=9)

    ax_c = make_ax([0.04, 0.04, 0.92, 0.88], border='#1B7A5A', bw=2)

    _primed = liq_state not in ('neutral', 'post_liquidation_cooldown')
    _sq_up  = fund_cur < -0.0001 or imb_1 > 1.3
    _sq_dn  = fund_cur >  0.0001 and imb_1 < 0.7
    _catalyst_word = 'short squeeze' if _sq_up else 'long squeeze' if _sq_dn else 'liquidation cascade'

    conc = [
        ('1. ON-CHAIN HEALTH SCORE', WHITE, True, 9.5),
        ('   [N/A] — Glassnode/CryptoQuant/LookIntoBitcoin not connected.', GRAY, False, 8.5),
        ('   Phase 2 needed: SOPR, NUPL, MVRV, Exchange Reserves, LTH, Whales, ETF.', GRAY, False, 8.5),
        ('', GRAY, False, 8),
        ('2. KEY SIGNAL (from available data)', WHITE, True, 9.5),
        (f'   {imb_label} 1%-zone imbalance: {imb_1:.2f}x MORE volume {imb_direction} than {"below" if imb_1>1 else "above"}.', YELLOW, True, 8.5),
        (f'   Zone 1: {z1_range}  Volume: ${z1_vol_b:.1f}B  Distance: +{na_dist:.2f}%', YELLOW, False, 8.5),
        (f'   Funding Rate: {fund_cur:+.5f}% (8h)  Z-score: {fund_z:+.2f} -> {fund_state}', RED if abs(fund_z)>1 else GRAY, True, 8.5),
        (f'   {fund_side} paying ~{fund_daily:.3f}% per day in funding — {"unsustainable" if abs(fund_daily)>1 else "moderate"} positioning.', RED if abs(fund_daily)>1 else GRAY, False, 8.5),
        (f'   If price moves to ${na:,.0f}, ${na_vol_b:.1f}B in {liq_cascade} liquidations cascade {squeeze_dir.lower()}.', RED, False, 8.5),
        ('', GRAY, False, 8),
        ('3. FORECAST (7-14 days horizon)', WHITE, True, 9.5),
        (f'   Dominant mechanical force: {squeeze_side} SQUEEZE risk (heatmap + funding)', GREEN if _sq_up else RED, False, 8.5),
        (f'   - Zone 1 at ${na:,.0f} is Liquidity Magnet — market has gravitational pull', GREEN if _sq_up else GRAY, False, 8.5),
        (f'   - Vacuum gap {vac_range} ({vac_pct_str}) enables fast price movement if triggered', GREEN if vac_range!='N/A' else GRAY, False, 8.5),
        (f'   COUNTERWEIGHT: Coinbase Premium = ${cb_prem:+.2f} ({cb_state}) -> {"no" if cb_prem<0 else "positive"} spot institutional flow', RED if cb_prem<0 else GREEN, False, 8.5),
        (f'   OI {oi_trend} ({oi_d24:+.2f}% 24h, {oi_d7d:+.2f}% 7d) -> market {oi_action}', RED if oi_d24<0 else GREEN, False, 8.5),
        (f'   CONCLUSION: {_catalyst_word.capitalize()} mechanics {"primed" if _primed else "neutral"} — {"lacks" if cb_prem<0 else "has"} spot demand confirmation.', YELLOW, True, 8.5),
        (f'   Key level: ${na:,.0f} (trigger). Sustained rally needs CB Premium > 0.', YELLOW, False, 8.5),
        ('', GRAY, False, 8),
        ('4. OPERATIONAL LEVELS', WHITE, True, 9.5),
        (f'   Long entry zone:       ${nb:,.0f} (nearest long-liq cluster, -{nb_dist:.2f}%)', GREEN, False, 8.5),
        (f'   Crowd stops (longs):   {crowd_stop_str}', RED, False, 8.5),
        (f'   Deep stop:             {deep_stop_str}', RED, False, 8.5),
        (f'   Liquidity Magnet:      ${na:,.0f} (+{na_dist:.2f}%) — Zone 1, ${na_vol_b:.1f}B', YELLOW, True, 8.5),
        (f'   Extended target:       {ext_target_str}', YELLOW, False, 8.5),
        (f'   Vacuum (fast pass):    {vac_range} ({vac_pct_str})', BLUE, False, 8.5),
        (f'   Support (key):         {crowd_stop_str} (floor)', RED, False, 8.5),
        ('', GRAY, False, 8),
        ('5. MARKET TYPE', WHITE, True, 9.5),
        (f'   liquidation_state: {liq_state.upper()}', YELLOW, True, 9),
        (f'   Type: {"PRIMED FOR " + _catalyst_word.upper() if _primed else "NEUTRAL/RANGE"} — {"fast directional move on catalyst" if _primed else "await catalyst"}', YELLOW, False, 8.5),
        ('', GRAY, False, 8),
        ('EDITORIAL REVIEW', WHITE, True, 9.5),
        (f'   Data confidence:    MEDIUM (derivatives only; no on-chain confirmation)', YELLOW, False, 8.5),
        (f'   Internal conflict:  Funding({"-" if fund_cur<0 else "+"}) signals squeeze {"UP" if fund_cur<0 else "DOWN"}; CB Premium({"+" if cb_prem>0 else "-"}) signals {"demand" if cb_prem>0 else "NO demand"}', RED if (fund_cur<0) == (cb_prem>0) else GRAY, False, 8.5),
        ('   Blind spots:        CVD, L/S Ratio, Orderbook, VWAP, all on-chain metrics.', GRAY, False, 8.5),
        ('   Recommendation:     Connect Phase 2 sources to complete the 9-layer module.', BLUE, True, 8.5),
    ]
    text_panel(ax_c, conc, dy=0.028)

    fig.text(0.5, 0.01,
             f'Generated: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")}  |  '
             f'CryptoDatEx  |  Source: CoinGlass (heatmap + derivatives)  |  On-chain: [N/A]',
             ha='center', color=GRAY, fontsize=8)

    pdf.savefig(fig, bbox_inches='tight'); plt.close(fig)
    print('  Page 6 done')

print(f'\nReport saved: {output_path}')
