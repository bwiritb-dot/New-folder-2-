"""
metrics_builder.py — Phase 1 metrics layer
Computes workbook-style analytics from raw CoinGlass payloads.

Sections produced: Heatmap, Derivatives, Signal
"""
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BUCKET_PCTS = [0.005, 0.01, 0.02, 0.03, 0.05]
TARGET_EXCHANGES_OI = {"Binance", "CME", "Bybit", "OKX"}
COLUMNS = [
    "section", "metric_key", "label", "timeframe",
    "value", "unit", "source", "status", "updated_at", "notes",
]


# ── Primitives ────────────────────────────────────────────────────────────────

def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _pn(v, d: int = 2) -> str:
    v = _f(v)
    if v is None:
        return "n/a"
    a = abs(v)
    if a >= 1e9:
        return f"{v/1e9:.{d}f}B"
    if a >= 1e6:
        return f"{v/1e6:.{d}f}M"
    if a >= 1e3:
        return f"{v/1e3:.{d}f}K"
    return f"{v:.{d}f}"


def _row(section, key, label, tf, value, unit="", source="", notes="") -> dict:
    v = str(value) if value not in (None, "n/a") else "n/a"
    return {
        "section": section,
        "metric_key": key,
        "label": label,
        "timeframe": tf,
        "value": v,
        "unit": unit,
        "source": source,
        "status": "ok" if v != "n/a" else "missing",
        "updated_at": _now_utc(),
        "notes": notes,
    }


# ── Heatmap parsing ───────────────────────────────────────────────────────────

def parse_heatmap_liq(raw: dict) -> list[dict]:
    """
    Parse the liq-format heatmap returned by fetch_heatmap.
    Response structure: {code, msg, data: {y, prices, liq, ...}}
      y      — price-level list
      prices — OHLCV rows [[ts, o, h, l, c], ...]
      liq    — [[time_idx, price_idx, volume], ...]
    """
    inner = raw.get("data") or raw
    y_levels  = inner.get("y") or []
    price_rows = inner.get("prices") or []
    liq        = inner.get("liq") or []

    if not y_levels or not price_rows or not liq:
        return []

    records = []
    for row in liq:
        if not isinstance(row, list) or len(row) < 3:
            continue
        ti, pi, vol = row[0], row[1], _f(row[2])
        if vol is None or vol <= 0:
            continue
        if not (0 <= ti < len(price_rows) and 0 <= pi < len(y_levels)):
            continue
        pr = price_rows[ti]
        ts    = int(pr[0]) if isinstance(pr, list) and pr else None
        price = _f(y_levels[pi])
        if ts is None or price is None:
            continue
        records.append({"price": price, "timestamp": ts, "volume": vol})
    return records


def extract_current_price_from_heatmap(raw: dict) -> float | None:
    """Return the close of the last OHLCV candle embedded in the heatmap payload."""
    inner = raw.get("data") or raw
    price_rows = inner.get("prices") or []
    if price_rows:
        last = price_rows[-1]
        if isinstance(last, list) and len(last) >= 5:
            return _f(last[4])
    return None


# ── Cluster analysis ──────────────────────────────────────────────────────────

def _build_pv(records: list[dict]) -> dict[float, float]:
    pv: dict[float, float] = defaultdict(float)
    for r in records:
        pv[r["price"]] += r["volume"]
    return dict(pv)


def _cluster(pv: dict[float, float]) -> list[dict]:
    if not pv:
        return []
    sp = sorted(pv)
    if len(sp) == 1:
        return [{"low": sp[0], "high": sp[0], "center": sp[0], "volume": pv[sp[0]], "n": 1}]

    gaps = [sp[i + 1] - sp[i] for i in range(len(sp) - 1)]
    max_gap = statistics.median(gaps) * 4

    clusters: list[dict] = []
    run = [sp[0]]
    vol = pv[sp[0]]
    for i in range(1, len(sp)):
        if sp[i] - sp[i - 1] <= max_gap:
            run.append(sp[i])
            vol += pv[sp[i]]
        else:
            clusters.append({
                "low": run[0], "high": run[-1],
                "center": (run[0] + run[-1]) / 2,
                "volume": vol, "n": len(run),
            })
            run, vol = [sp[i]], pv[sp[i]]
    clusters.append({
        "low": run[0], "high": run[-1],
        "center": (run[0] + run[-1]) / 2,
        "volume": vol, "n": len(run),
    })
    return clusters


def compute_heatmap_metrics(records: list[dict], current_price: float, tf: str) -> list[dict]:
    if not records or not current_price:
        return []
    src = "liqHeatMap"
    pv = _build_pv(records)
    clusters = sorted(_cluster(pv), key=lambda c: c["volume"], reverse=True)
    below = sorted([c for c in clusters if c["center"] < current_price],  key=lambda c: c["volume"], reverse=True)
    above = sorted([c for c in clusters if c["center"] >= current_price], key=lambda c: c["volume"], reverse=True)
    rows: list[dict] = []

    # Top-5 zones
    for rank, c in enumerate(clusters[:5], 1):
        side = "below" if c["center"] < current_price else "above"
        dpct = abs(c["center"] - current_price) / current_price * 100
        rows += [
            _row("Heatmap", f"top_zone_{rank}_vol_{tf}",   f"Top Zone {rank} Volume ({tf})",
                 tf, round(c["volume"], 2), "USD", src,
                 f"${c['low']:,.0f}-${c['high']:,.0f} | {side} | {dpct:.2f}% from price"),
            _row("Heatmap", f"top_zone_{rank}_range_{tf}", f"Top Zone {rank} Range ({tf})",
                 tf, f"${c['low']:,.0f}-${c['high']:,.0f}", "", src,
                 f"center=${c['center']:,.0f}, {side}, dist={dpct:.2f}%"),
        ]

    # Long liq zones below (3 largest)
    for rank, c in enumerate(below[:3], 1):
        dpct = (current_price - c["center"]) / current_price * 100
        rows.append(_row("Heatmap", f"long_liq_zone_{rank}_{tf}", f"Long Liq Zone {rank} Below ({tf})",
                         tf, round(c["volume"], 2), "USD", src,
                         f"${c['low']:,.0f}-${c['high']:,.0f} | {dpct:.2f}% below"))

    # Short liq zones above (3 largest)
    for rank, c in enumerate(above[:3], 1):
        dpct = (c["center"] - current_price) / current_price * 100
        rows.append(_row("Heatmap", f"short_liq_zone_{rank}_{tf}", f"Short Liq Zone {rank} Above ({tf})",
                         tf, round(c["volume"], 2), "USD", src,
                         f"${c['low']:,.0f}-${c['high']:,.0f} | {dpct:.2f}% above"))

    # Nearest cluster below / above
    nb = min(below, key=lambda c: current_price - c["center"], default=None)
    na = min(above, key=lambda c: c["center"] - current_price, default=None)
    if nb:
        dpct = (current_price - nb["center"]) / current_price * 100
        rows += [
            _row("Heatmap", f"nearest_below_price_{tf}", f"Nearest Cluster Below ({tf})",
                 tf, f"${nb['center']:,.0f}", "USD", src, f"dist={dpct:.2f}%, vol={_pn(nb['volume'])}"),
            _row("Heatmap", f"nearest_below_dist_{tf}", f"Nearest Below Dist ({tf})",
                 tf, round(dpct, 3), "%", src),
            _row("Heatmap", f"nearest_below_vol_{tf}", f"Nearest Below Volume ({tf})",
                 tf, round(nb["volume"], 2), "USD", src),
        ]
    if na:
        dpct = (na["center"] - current_price) / current_price * 100
        rows += [
            _row("Heatmap", f"nearest_above_price_{tf}", f"Nearest Cluster Above ({tf})",
                 tf, f"${na['center']:,.0f}", "USD", src, f"dist={dpct:.2f}%, vol={_pn(na['volume'])}"),
            _row("Heatmap", f"nearest_above_dist_{tf}", f"Nearest Above Dist ({tf})",
                 tf, round(dpct, 3), "%", src),
            _row("Heatmap", f"nearest_above_vol_{tf}", f"Nearest Above Volume ({tf})",
                 tf, round(na["volume"], 2), "USD", src),
        ]

    # Liquidity magnet: largest cluster among the 5 nearest by distance
    by_dist = sorted(clusters, key=lambda c: abs(c["center"] - current_price))
    magnet = max(by_dist[:5], key=lambda c: c["volume"], default=None)
    if magnet:
        side = "below" if magnet["center"] < current_price else "above"
        dpct = abs(magnet["center"] - current_price) / current_price * 100
        rows.append(_row("Heatmap", f"liquidity_magnet_{tf}", f"Liquidity Magnet ({tf})",
                         tf, f"${magnet['center']:,.0f}", "USD", src,
                         f"{side}, dist={dpct:.2f}%, vol={_pn(magnet['volume'])}"))

    # Liquidity vacuum: largest gap between cluster centers
    if len(clusters) >= 2:
        centers = sorted(c["center"] for c in clusters)
        gap_size, g_lo, g_hi = max(
            ((centers[i + 1] - centers[i], centers[i], centers[i + 1]) for i in range(len(centers) - 1)),
            key=lambda t: t[0],
        )
        rows.append(_row("Heatmap", f"liquidity_vacuum_{tf}", f"Liquidity Vacuum Gap ({tf})",
                         tf, round(gap_size, 0), "USD", src,
                         f"${g_lo:,.0f}-${g_hi:,.0f} | {gap_size/current_price*100:.2f}% of price"))

    # Distance buckets
    for pct in BUCKET_PCTS:
        lo, hi = current_price * (1 - pct), current_price * (1 + pct)
        bv = sum(v for p, v in pv.items() if lo <= p < current_price)
        av = sum(v for p, v in pv.items() if current_price <= p <= hi)
        imb = round(av / bv, 4) if bv > 0 else None
        lbl = f"{pct*100:.1f}%"
        rows += [
            _row("Heatmap", f"bucket_{lbl}_below_{tf}", f"Vol {lbl} Below ({tf})",   tf, round(bv, 2), "USD", src),
            _row("Heatmap", f"bucket_{lbl}_above_{tf}", f"Vol {lbl} Above ({tf})",   tf, round(av, 2), "USD", src),
            _row("Heatmap", f"bucket_{lbl}_imbalance_{tf}", f"Imbalance {lbl} ({tf})", tf, imb, "above/below", src,
                 ">1=more above, <1=more below"),
        ]

    rows += [
        _row("Heatmap", f"cluster_count_{tf}",  f"Cluster Count ({tf})",        tf, len(clusters),                  "", src),
        _row("Heatmap", f"total_volume_{tf}",   f"Total Heatmap Volume ({tf})", tf, round(sum(pv.values()), 2), "USD", src),
    ]
    return rows


# ── Funding metrics ───────────────────────────────────────────────────────────

def compute_funding_metrics(funding_raw: dict | None) -> list[dict]:
    if not funding_raw:
        return []
    src = "fundingRate/v2/history/chart"
    dm = funding_raw.get("dataMap") or {}
    dl = funding_raw.get("dateList") or []
    if not dm or not dl:
        return []

    n = len(dl)
    agg = []
    for i in range(n):
        vals = [v[i] for v in dm.values() if isinstance(v, list) and i < len(v) and _f(v[i]) is not None]
        agg.append(sum(vals) / len(vals) if vals else None)

    valid = [r for r in agg if r is not None]
    if not valid:
        return []

    cur = valid[-1]
    avg_24h = sum(valid[-3:]) / len(valid[-3:]) if valid[-3:] else None   # 3 × 8h = 24h
    avg_7d  = sum(valid[-21:]) / len(valid[-21:]) if valid[-21:] else None # 21 × 8h = 7d

    zscore = None
    if len(valid) >= 10:
        mu = sum(valid) / len(valid)
        sd = statistics.stdev(valid)
        zscore = (cur - mu) / sd if sd > 0 else 0.0

    if cur > 0.0002:    state = "overheated_long"
    elif cur > 0:       state = "mildly_bullish"
    elif cur < -0.0002: state = "overheated_short"
    elif cur < 0:       state = "mildly_bearish"
    else:               state = "neutral"

    return [
        _row("Derivatives", "funding_current",  "Current Funding Rate",  "8h",  round(cur * 100, 5),                         "%", src),
        _row("Derivatives", "funding_avg_24h",  "Funding Rate Avg 24h",  "24h", round(avg_24h * 100, 5) if avg_24h else None, "%", src),
        _row("Derivatives", "funding_avg_7d",   "Funding Rate Avg 7d",   "7d",  round(avg_7d  * 100, 5) if avg_7d  else None, "%", src),
        _row("Derivatives", "funding_zscore",   "Funding Rate Z-Score",  "all", round(zscore, 3) if zscore is not None else None, "sigma", src, "vs full history window"),
        _row("Derivatives", "funding_state",    "Funding State",         "current", state, "", src),
    ]


# ── OI metrics ────────────────────────────────────────────────────────────────

def compute_oi_metrics(oi_chart_raw: dict | None, oi_info_raw: list | None) -> list[dict]:
    rows: list[dict] = []
    src = "openInterest"

    if oi_chart_raw:
        dm = oi_chart_raw.get("dataMap") or {}
        dl = oi_chart_raw.get("dateList") or []
        n  = len(dl)
        if n and dm:
            totals = []
            for i in range(n):
                vals = [v[i] for v in dm.values() if isinstance(v, list) and i < len(v) and _f(v[i]) is not None]
                totals.append(sum(vals) if vals else None)
            valid = [(dl[i], totals[i]) for i in range(n) if totals[i] is not None]
            if valid:
                cur_oi = valid[-1][1]
                d24h = (cur_oi - valid[max(0, len(valid) - 4)][1]) / valid[max(0, len(valid) - 4)][1] * 100 if len(valid) >= 4 else None
                d7d  = (cur_oi - valid[max(0, len(valid) - 22)][1]) / valid[max(0, len(valid) - 22)][1] * 100 if len(valid) >= 22 else None
                rows += [
                    _row("Derivatives", "oi_total_current", "Total OI (All Exchanges)", "current", round(cur_oi, 0), "USD", src),
                    _row("Derivatives", "oi_delta_24h",     "OI Chg24h",                  "24h", round(d24h, 3) if d24h else None, "%", src),
                    _row("Derivatives", "oi_delta_7d",      "OI Chg7d",                   "7d",  round(d7d,  3) if d7d  else None, "%", src),
                ]

    if isinstance(oi_info_raw, list):
        for item in oi_info_raw:
            ex = item.get("exchangeName", "")
            if ex in TARGET_EXCHANGES_OI:
                rows += [
                    _row("Derivatives", f"oi_{ex.lower()}",         f"OI {ex}",       "current", _f(item.get("openInterest")), "USD", src),
                    _row("Derivatives", f"oi_{ex.lower()}_24h_chg", f"OI {ex} Chg24h",  "24h",     _f(item.get("h24Change")),    "%",   src),
                ]

    return rows


# ── Coinbase premium metrics ──────────────────────────────────────────────────

def compute_coinbase_premium_metrics(premium_raw) -> list[dict]:
    if not premium_raw:
        return []
    src = "kline/coinbase_premium"
    data = premium_raw if isinstance(premium_raw, list) else (premium_raw.get("data") or [])
    closes = [_f(row[4]) for row in data if isinstance(row, list) and len(row) >= 5 and _f(row[4]) is not None]
    if not closes:
        return []

    cur   = closes[-1]
    avg_1h  = sum(closes[-2:])  / len(closes[-2:])  if len(closes) >= 2 else cur
    avg_24h = sum(closes[-48:]) / len(closes[-48:]) if len(closes) >= 2 else cur
    state = "positive" if cur > 0.02 else "negative" if cur < -0.02 else "neutral"

    return [
        _row("Derivatives", "coinbase_premium_current", "Coinbase Premium",       "current", round(cur,     5), "%", src),
        _row("Derivatives", "coinbase_premium_1h",      "Coinbase Premium 1h avg","1h",      round(avg_1h,  5), "%", src),
        _row("Derivatives", "coinbase_premium_24h",     "Coinbase Premium 24h avg","24h",    round(avg_24h, 5), "%", src),
        _row("Derivatives", "coinbase_premium_state",   "Coinbase Premium State", "current", state,             "", src),
    ]


# ── Liquidation chart metrics (long vs short volumes by TF) ──────────────────

def compute_liq_chart_metrics(raw) -> list[dict]:
    """
    Handles two formats:
      OLD: dict with dataMap / dateList (longList, shortList per exchange)
      NEW: list of {createTime, buyVolUsd (=short liq), sellVolUsd (=long liq), ...}
    """
    if not raw:
        return []
    src = "CoinGlass/liq_chart"

    # ── NEW format: list of {createTime, buyVolUsd, sellVolUsd} ──────────────
    if isinstance(raw, list):
        records = raw
        # buyVolUsd = shorts liquidated (force-buy to close short)
        # sellVolUsd = longs liquidated (force-sell to close long)
        sell_usd = [_f(r.get("sellVolUsd", 0)) or 0 for r in records]   # long liqs
        buy_usd  = [_f(r.get("buyVolUsd",  0)) or 0 for r in records]   # short liqs

        liq_24h_long  = sum(sell_usd[-48:]) if len(sell_usd) >= 2 else sum(sell_usd)
        liq_24h_short = sum(buy_usd[-48:])  if len(buy_usd)  >= 2 else sum(buy_usd)
        liq_1h_long   = sum(sell_usd[-2:])
        liq_1h_short  = sum(buy_usd[-2:])
        liq_4h_long   = sum(sell_usd[-8:])
        liq_4h_short  = sum(buy_usd[-8:])
        total_24h     = liq_24h_long + liq_24h_short
        ls_ratio_24h  = round(liq_24h_long / liq_24h_short, 4) if liq_24h_short > 0 else None

        rows = [
            _row("Derivatives", "liq_long_24h",  "Long Liq 24h",  "24h", round(liq_24h_long,  2), "USD", src),
            _row("Derivatives", "liq_short_24h", "Short Liq 24h", "24h", round(liq_24h_short, 2), "USD", src),
            _row("Derivatives", "liq_total_24h", "Total Liq 24h", "24h", round(total_24h,     2), "USD", src),
            _row("Derivatives", "liq_long_4h",   "Long Liq 4h",   "4h",  round(liq_4h_long,   2), "USD", src),
            _row("Derivatives", "liq_short_4h",  "Short Liq 4h",  "4h",  round(liq_4h_short,  2), "USD", src),
            _row("Derivatives", "liq_long_1h",   "Long Liq 1h",   "1h",  round(liq_1h_long,   2), "USD", src),
            _row("Derivatives", "liq_short_1h",  "Short Liq 1h",  "1h",  round(liq_1h_short,  2), "USD", src),
        ]
        if ls_ratio_24h is not None:
            rows.append(_row("Derivatives", "liq_ls_ratio_24h", "Liq Long/Short Ratio 24h", "24h",
                             ls_ratio_24h, "ratio", src, notes=">1 = more longs liquidated"))
        return rows

    # ── OLD format: dict with dataMap / dateList ──────────────────────────────
    inner = raw
    if isinstance(inner, dict) and "data" in inner and isinstance(inner["data"], dict):
        inner = inner["data"]

    date_list = inner.get("dateList") or []
    data_map  = inner.get("dataMap") or {}
    if not date_list or not data_map:
        return []

    total_longs  = [0.0] * len(date_list)
    total_shorts = [0.0] * len(date_list)
    for _exch, exch_data in data_map.items():
        if not isinstance(exch_data, dict):
            continue
        for i, v in enumerate(exch_data.get("longList") or []):
            if i < len(total_longs) and v:
                total_longs[i] += float(v)
        for i, v in enumerate(exch_data.get("shortList") or []):
            if i < len(total_shorts) and v:
                total_shorts[i] += float(v)

    if not any(total_longs) and not any(total_shorts):
        return []

    liq_24h_long  = sum(total_longs[-48:])  if len(total_longs)  >= 2 else sum(total_longs)
    liq_24h_short = sum(total_shorts[-48:]) if len(total_shorts) >= 2 else sum(total_shorts)
    liq_1h_long   = sum(total_longs[-2:])
    liq_1h_short  = sum(total_shorts[-2:])
    liq_4h_long   = sum(total_longs[-8:])
    liq_4h_short  = sum(total_shorts[-8:])
    total_24h     = liq_24h_long + liq_24h_short
    ls_ratio_24h  = round(liq_24h_long / liq_24h_short, 4) if liq_24h_short > 0 else None

    rows = [
        _row("Derivatives", "liq_long_24h",  "Long Liq 24h",  "24h", round(liq_24h_long,  2), "USD", src),
        _row("Derivatives", "liq_short_24h", "Short Liq 24h", "24h", round(liq_24h_short, 2), "USD", src),
        _row("Derivatives", "liq_total_24h", "Total Liq 24h", "24h", round(total_24h,     2), "USD", src),
        _row("Derivatives", "liq_long_4h",   "Long Liq 4h",   "4h",  round(liq_4h_long,   2), "USD", src),
        _row("Derivatives", "liq_short_4h",  "Short Liq 4h",  "4h",  round(liq_4h_short,  2), "USD", src),
        _row("Derivatives", "liq_long_1h",   "Long Liq 1h",   "1h",  round(liq_1h_long,   2), "USD", src),
        _row("Derivatives", "liq_short_1h",  "Short Liq 1h",  "1h",  round(liq_1h_short,  2), "USD", src),
    ]
    if ls_ratio_24h is not None:
        rows.append(_row("Derivatives", "liq_ls_ratio_24h", "Liq Long/Short Ratio 24h", "24h",
                         ls_ratio_24h, "ratio", src, notes=">1 = more longs liquidated"))
    return rows


# ── Liquidation today snapshot ────────────────────────────────────────────────

def compute_liq_today_metrics(raw) -> list[dict]:
    """
    Parse /api/futures/liquidation/today response.
    Fields: longLiquidationUsd, shortLiquidationUsd, liquidationUsd,
            longLiquidationRate, shortLiquidationRate, liquidationTraders, avg7dRate.
    """
    if not raw or not isinstance(raw, dict):
        return []
    src = "CoinGlass/liq_today"
    rows = []

    def _add(key, label, tf, val, unit="USD"):
        v = _f(raw.get(val))
        if v is not None:
            rows.append(_row("Derivatives", key, label, tf, round(v, 2), unit, src))

    _add("liq_today_long_usd",  "Long Liq Today",        "today", "longLiquidationUsd")
    _add("liq_today_short_usd", "Short Liq Today",       "today", "shortLiquidationUsd")
    _add("liq_today_total_usd", "Total Liq Today",       "today", "liquidationUsd")
    _add("liq_today_long_rate", "Long Liq Rate Today %", "today", "longLiquidationRate",  "%")
    _add("liq_today_short_rate","Short Liq Rate Today %","today", "shortLiquidationRate", "%")
    _add("liq_today_traders",   "Liquidated Traders",    "today", "liquidationTraders",   "count")
    _add("liq_today_max_order", "Max Single Liq",        "today", "maxLiquidationVolUsd")
    _add("liq_today_avg_7d",    "7d Avg Liq Rate",       "7d",    "avg7dRate",            "%")
    return rows


# ── Long/Short ratio metrics ──────────────────────────────────────────────────

def compute_long_short_ratio_metrics(raw) -> list[dict]:
    """
    Handles two formats:
      OLD: dict with dataMap (longList/shortList per exchange) + dateList
      NEW: dict with longRateList, shortsRateList, longShortRateList, dateList (from longShortChart)
    """
    if not raw:
        return []
    src = "CoinGlass/longShortRatio"

    inner = raw
    if isinstance(inner, dict) and "data" in inner and isinstance(inner["data"], dict):
        inner = inner["data"]

    if not isinstance(inner, dict):
        return []

    # ── NEW format: longRateList / shortsRateList directly in dict ────────────
    if "longRateList" in inner:
        long_list  = inner.get("longRateList",  [])
        short_list = inner.get("shortsRateList", [])
        ls_list    = inner.get("longShortRateList", [])
        if not long_list:
            return []
        cur_long  = _f(long_list[-1])
        cur_short = _f(short_list[-1]) if short_list else None
        cur_ls    = _f(ls_list[-1]) if ls_list else None
        avg_long  = sum(_f(v) or 0 for v in long_list[-30:]) / min(30, len(long_list))

        rows = [
            _row("Derivatives", "ls_ratio_long_pct",     "Long Accounts %",      "current",
                 round(cur_long, 2) if cur_long else "n/a",   "%", src),
            _row("Derivatives", "ls_ratio_short_pct",    "Short Accounts %",     "current",
                 round(cur_short, 2) if cur_short else "n/a", "%", src),
            _row("Derivatives", "ls_ratio_long_30d_avg", "Long % 30-pt avg",     "30d",
                 round(avg_long, 2), "%", src),
        ]
        if cur_ls is not None:
            rows.append(_row("Derivatives", "ls_ratio_current", "L/S Ratio (long/short)", "current",
                             round(cur_ls, 4), "ratio", src, notes=">1 = more longs than shorts"))
        return rows

    # ── OLD format: dataMap with longList / shortList ─────────────────────────
    date_list = inner.get("dateList") or []
    data_map  = inner.get("dataMap") or {}
    if not date_list or not data_map:
        return []

    series = data_map.get("All") or data_map.get("all") or next(iter(data_map.values()), None)
    if not series or not isinstance(series, dict):
        return []

    long_list  = series.get("longList")  or series.get("buyList")  or []
    short_list = series.get("shortList") or series.get("sellList") or []
    if not long_list:
        return []

    cur_long  = _f(long_list[-1])
    cur_short = _f(short_list[-1]) if short_list else (1 - cur_long if cur_long else None)
    if cur_long is None:
        return []
    avg_long_24h = sum(_f(v) or 0 for v in long_list[-48:]) / min(48, len(long_list))

    return [
        _row("Derivatives", "ls_ratio_long_pct",     "Long Accounts %",   "current", round(cur_long * 100, 2),        "%", src),
        _row("Derivatives", "ls_ratio_short_pct",    "Short Accounts %",  "current", round((cur_short or 0) * 100, 2), "%", src),
        _row("Derivatives", "ls_ratio_long_24h_avg", "Long % 24h avg",    "24h",     round(avg_long_24h * 100, 2),     "%", src),
    ]


# ── Taker buy/sell metrics (now sourced from liq/chart buyVolUsd/sellVolUsd) ─

def compute_taker_buy_sell_metrics(raw) -> list[dict]:
    """
    Handles two formats:
      OLD: dict with dataMap (buyList/sellList per exchange) + dateList
      NEW: list of {createTime, buyVolUsd (=short liq force-buys), sellVolUsd (=long liq force-sells)}
    """
    if not raw:
        return []
    src = "CoinGlass/takerBuySell"

    # ── NEW format: list of {buyVolUsd, sellVolUsd} ───────────────────────────
    if isinstance(raw, list):
        buy_list  = [_f(r.get("buyVolUsd",  0)) or 0 for r in raw]
        sell_list = [_f(r.get("sellVolUsd", 0)) or 0 for r in raw]
        if not any(buy_list) and not any(sell_list):
            return []
        buy_24h  = sum(buy_list[-48:])
        sell_24h = sum(sell_list[-48:])
        buy_1h   = sum(buy_list[-2:])
        sell_1h  = sum(sell_list[-2:])
        ratio_24h = round(buy_24h / sell_24h, 4) if sell_24h > 0 else None
        ratio_1h  = round(buy_1h  / sell_1h,  4) if sell_1h  > 0 else None
        rows = [
            _row("Derivatives", "taker_buy_24h",  "Liq Buy Vol 24h",  "24h", round(buy_24h,  2), "USD", src,
                 notes="short-liq force-buys"),
            _row("Derivatives", "taker_sell_24h", "Liq Sell Vol 24h", "24h", round(sell_24h, 2), "USD", src,
                 notes="long-liq force-sells"),
            _row("Derivatives", "taker_buy_1h",   "Liq Buy Vol 1h",   "1h",  round(buy_1h,   2), "USD", src),
            _row("Derivatives", "taker_sell_1h",  "Liq Sell Vol 1h",  "1h",  round(sell_1h,  2), "USD", src),
        ]
        if ratio_24h is not None:
            rows.append(_row("Derivatives", "taker_ratio_24h", "Liq Buy/Sell Ratio 24h", "24h",
                             ratio_24h, "ratio", src, notes=">1 = more short liqs than long liqs"))
        if ratio_1h is not None:
            rows.append(_row("Derivatives", "taker_ratio_1h", "Liq Buy/Sell Ratio 1h", "1h",
                             ratio_1h, "ratio", src))
        return rows

    # ── OLD format: dict with dataMap ─────────────────────────────────────────
    inner = raw
    if isinstance(inner, dict) and "data" in inner and isinstance(inner["data"], dict):
        inner = inner["data"]
    if not isinstance(inner, dict):
        return []

    date_list = inner.get("dateList") or []
    data_map  = inner.get("dataMap") or {}
    if not date_list or not data_map:
        return []

    buy_list = sell_list = []
    for _exch, exch_data in data_map.items():
        if not isinstance(exch_data, dict):
            continue
        bl = exch_data.get("buyList")  or exch_data.get("longList")  or []
        sl = exch_data.get("sellList") or exch_data.get("shortList") or []
        if len(bl) > len(buy_list):
            buy_list, sell_list = bl, sl

    if not buy_list:
        return []

    buy_24h   = sum(_f(v) or 0 for v in buy_list[-48:])
    sell_24h  = sum(_f(v) or 0 for v in sell_list[-48:]) if sell_list else 0
    ratio_24h = round(buy_24h / sell_24h, 4) if sell_24h > 0 else None
    buy_1h    = sum(_f(v) or 0 for v in buy_list[-2:])
    sell_1h   = sum(_f(v) or 0 for v in sell_list[-2:]) if sell_list else 0
    ratio_1h  = round(buy_1h / sell_1h, 4) if sell_1h > 0 else None

    rows = [
        _row("Derivatives", "taker_buy_24h",  "Taker Buy 24h",  "24h", round(buy_24h,  2), "USD", src),
        _row("Derivatives", "taker_sell_24h", "Taker Sell 24h", "24h", round(sell_24h, 2), "USD", src),
        _row("Derivatives", "taker_buy_1h",   "Taker Buy 1h",   "1h",  round(buy_1h,   2), "USD", src),
        _row("Derivatives", "taker_sell_1h",  "Taker Sell 1h",  "1h",  round(sell_1h,  2), "USD", src),
    ]
    if ratio_24h is not None:
        rows.append(_row("Derivatives", "taker_ratio_24h", "Taker Buy/Sell Ratio 24h", "24h",
                         ratio_24h, "ratio", src, notes=">1 = buyers dominate"))
    if ratio_1h is not None:
        rows.append(_row("Derivatives", "taker_ratio_1h", "Taker Buy/Sell Ratio 1h", "1h",
                         ratio_1h, "ratio", src, notes=">1 = buyers dominate"))
    return rows


# ── ETF flow metrics ──────────────────────────────────────────────────────────

def compute_etf_flow_metrics(raw) -> list[dict]:
    if not raw:
        return []
    src = "farside.co.uk"

    totals_30d = raw.get("last_30d_totals_m") or {}
    if not totals_30d:
        return []

    all_tickers = {k: v for k, v in totals_30d.items() if k and k != "Total"}
    total_net = sum(all_tickers.values())

    sorted_tickers = sorted(all_tickers.items(), key=lambda x: x[1], reverse=True)

    rows = [
        _row("ETF", "etf_net_flow_30d", "ETF Net Flow 30d", "30d",
             round(total_net, 2), "M USD", src, notes="sum all BTC spot ETFs"),
    ]

    # Top 3 by absolute flow (positive = inflow leaders)
    for rank, (ticker, flow_m) in enumerate(sorted_tickers[:3], 1):
        rows.append(_row("ETF", f"etf_top{rank}_ticker", f"ETF Top{rank} Ticker", "30d",
                         ticker, "", src))
        rows.append(_row("ETF", f"etf_top{rank}_flow_30d", f"ETF Top{rank} Flow 30d", "30d",
                         round(flow_m, 2), "M USD", src))

    # Bottom 3 (outflow)
    bottom3 = sorted(all_tickers.items(), key=lambda x: x[1])[:3]
    for rank, (ticker, flow_m) in enumerate(bottom3, 1):
        rows.append(_row("ETF", f"etf_bot{rank}_ticker", f"ETF Bot{rank} Ticker", "30d",
                         ticker, "", src))
        rows.append(_row("ETF", f"etf_bot{rank}_flow_30d", f"ETF Bot{rank} Flow 30d", "30d",
                         round(flow_m, 2), "M USD", src))

    return rows


# ── Signal metrics ────────────────────────────────────────────────────────────

def compute_signal_metrics(all_rows: list[dict]) -> list[dict]:
    def find(key):
        for r in all_rows:
            if r["metric_key"] == key:
                return _f(r["value"]) if r["value"] != "n/a" else r["value"]
        return None

    imb_1pct     = find("bucket_1.0%_imbalance_24h")
    oi_delta     = find("oi_delta_24h")
    fund_state   = next((r["value"] for r in all_rows if r["metric_key"] == "funding_state"), None)

    if isinstance(imb_1pct, float):
        liq_bias = "short_pressure" if imb_1pct > 1.2 else "long_pressure" if imb_1pct < 0.8 else "balanced"
    else:
        liq_bias = "unknown"

    if fund_state == "overheated_long"  and liq_bias == "long_pressure"  and (oi_delta or 0) > 2:
        liq_state = "squeeze_risk_long"
    elif fund_state == "overheated_short" and liq_bias == "short_pressure" and (oi_delta or 0) < -2:
        liq_state = "squeeze_risk_short"
    else:
        liq_state = "neutral"

    return [
        _row("Signal", "liquidation_direction_bias", "Liquidation Direction Bias", "current",
             liq_bias, "", "computed", "based on 1% bucket imbalance (24h)"),
        _row("Signal", "liquidation_state", "Liquidation State", "current",
             liq_state, "", "computed", "funding + imbalance + OI delta"),
    ]


# ── Master builder ────────────────────────────────────────────────────────────

def build_summary_metrics(bundle: dict) -> list[dict]:
    """
    Assemble all metric rows from the raw-payload bundle.

    Required bundle keys:
      current_price        float | None
      heatmap_24h_raw      raw heatmap dict (fetch_heatmap 5m×288)
      heatmap_3d_raw       raw heatmap dict (fetch_heatmap 15m×288)
      heatmap_7d_raw       raw heatmap dict (fetch_heatmap 60m×168)
      funding_raw          fetch_funding_rate_history() result
      oi_chart_raw         fetch_oi_chart_v3() result
      oi_info_raw          fetch_oi_info() result  (list)
      coinbase_premium_raw fetch_kline_coinbase_premium() result
      liq_chart_raw        fetch_liquidation_chart() result
      long_short_ratio_raw fetch_long_short_ratio() result
      taker_buy_sell_raw   fetch_taker_buy_sell() result
      etf_flows_raw        fetch_etf_flows() result
    """
    rows: list[dict] = []
    cp = bundle.get("current_price")

    if cp:
        rows.append(_row("Heatmap", "current_price", "Current BTC Price", "current", round(cp, 2), "USD", "Binance"))

    for tf, key in [("24h", "heatmap_24h_raw"), ("3d", "heatmap_3d_raw"), ("7d", "heatmap_7d_raw")]:
        raw = bundle.get(key)
        if raw and cp:
            records = parse_heatmap_liq(raw)
            if records:
                rows.extend(compute_heatmap_metrics(records, cp, tf))

    rows.extend(compute_funding_metrics(bundle.get("funding_raw")))
    rows.extend(compute_oi_metrics(bundle.get("oi_chart_raw"), bundle.get("oi_info_raw")))
    rows.extend(compute_coinbase_premium_metrics(bundle.get("coinbase_premium_raw")))
    rows.extend(compute_liq_today_metrics(bundle.get("liq_today_raw")))
    rows.extend(compute_liq_chart_metrics(bundle.get("liq_chart_raw")))
    rows.extend(compute_long_short_ratio_metrics(bundle.get("long_short_ratio_raw")))
    rows.extend(compute_taker_buy_sell_metrics(bundle.get("taker_buy_sell_raw")))
    rows.extend(compute_etf_flow_metrics(bundle.get("etf_flows_raw")))
    rows.extend(compute_signal_metrics(rows))
    return rows


# ── Export ────────────────────────────────────────────────────────────────────

def save_summary_metrics(rows: list[dict], output_dir: Path, ts: str) -> None:
    if not rows:
        return
    csv_path  = output_dir / f"summary_metrics_{ts}.csv"
    json_path = output_dir / f"summary_metrics_{ts}.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
