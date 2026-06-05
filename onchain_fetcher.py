"""
onchain_fetcher.py — Public On-Chain Data Fetcher
==================================================
Fetches BTC on-chain metrics from FREE public APIs:
  - mempool.space  : hashrate, difficulty, fees, mempool
  - alternative.me : Fear & Greed Index (sentiment proxy)
  - blockchain.info: tx count, active address proxy
  - CoinGecko      : market cap, realized cap proxy, MVRV approx

All values include a timestamp and [N/A] fallback per CryptoDatEx rules.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from coinglass_analyzer import fetch_all_onchain_coinglass as _fetch_cg_onchain
    _HAS_COINGLASS = True
except ImportError:
    _HAS_COINGLASS = False

log = logging.getLogger(__name__)

_TS = lambda: datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; CryptoDatEx/1.0)"})

CACHE_FILE = Path("output") / "onchain_cache.json"


def _get(url, params=None, timeout=12) -> dict | list | None:
    try:
        r = _SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"  [onchain] {url} → {e}")
        return None


# ─── Fear & Greed Index (alternative.me) ────────────────────────────────────

def fetch_fear_greed() -> dict:
    """
    Returns: {value: 0-100, classification: str, timestamp: str}
    Proxy for NUPL / market sentiment.
    """
    data = _get("https://api.alternative.me/fng/?limit=8&format=json")
    result = {"fear_greed_current": "N/A", "fear_greed_label": "N/A",
              "fear_greed_7d_avg": "N/A", "timestamp": _TS()}
    if not data or "data" not in data:
        return result
    pts = data["data"]
    if pts:
        result["fear_greed_current"] = int(pts[0]["value"])
        result["fear_greed_label"]   = pts[0]["value_classification"]
    vals = [int(p["value"]) for p in pts if p.get("value")]
    if vals:
        result["fear_greed_7d_avg"] = round(sum(vals) / len(vals), 1)
    return result


# ─── Mempool.space ──────────────────────────────────────────────────────────

def fetch_mempool_stats() -> dict:
    result = {
        "mempool_count": "N/A", "mempool_vsize_mb": "N/A",
        "fee_low": "N/A", "fee_mid": "N/A", "fee_high": "N/A",
        "timestamp": _TS(),
    }
    data = _get("https://mempool.space/api/mempool")
    if data:
        result["mempool_count"]    = data.get("count", "N/A")
        vsize = data.get("vsize")
        if vsize:
            result["mempool_vsize_mb"] = round(vsize / 1e6, 2)

    fees = _get("https://mempool.space/api/v1/fees/recommended")
    if fees:
        result["fee_low"]  = fees.get("economyFee", "N/A")
        result["fee_mid"]  = fees.get("halfHourFee", "N/A")
        result["fee_high"] = fees.get("fastestFee", "N/A")

    return result


def fetch_hashrate() -> dict:
    result = {
        "hashrate_eh": "N/A", "hashrate_1w_ago_eh": "N/A",
        "difficulty": "N/A", "next_adj_pct": "N/A",
        "blocks_until_adj": "N/A", "puell_multiple": "N/A",
        "timestamp": _TS(),
    }
    # Hashrate 1-month series
    hr = _get("https://mempool.space/api/v1/mining/hashrate/1m")
    if hr and "hashrates" in hr:
        pts = hr["hashrates"]
        if pts:
            result["hashrate_eh"] = round(pts[-1]["avgHashrate"] / 1e18, 2)
        if len(pts) >= 7:
            result["hashrate_1w_ago_eh"] = round(pts[-7]["avgHashrate"] / 1e18, 2)

    # Difficulty adjustment
    adj = _get("https://mempool.space/api/v1/difficulty-adjustment")
    if adj:
        result["difficulty"]      = adj.get("currentDifficulty", "N/A")
        result["next_adj_pct"]    = round(adj.get("difficultyChange", 0), 2)
        result["blocks_until_adj"] = adj.get("remainingBlocks", "N/A")

    # Puell Multiple proxy: current block subsidy reward revenue vs 365d avg
    # Using price to estimate: Puell = (daily miner revenue in USD) / (365d avg)
    # We'll flag as N/A — full Puell needs historical price series
    result["puell_multiple"] = "N/A (needs price series)"

    return result


def fetch_block_stats() -> dict:
    """Active-address proxy via daily confirmed tx count + block stats."""
    result = {
        "tx_count_24h": "N/A", "active_addr_proxy": "N/A",
        "avg_block_size_kb": "N/A", "timestamp": _TS(),
    }
    # Use /api/v1/blocks — returns most recent 15 blocks; fetch multiple pages
    blocks = []
    try:
        tip = _get("https://mempool.space/api/blocks")
        if tip and isinstance(tip, list):
            blocks.extend(tip)
            # ~144 blocks/24h; get up to 10 pages of 15 blocks
            height = min(b.get("height", 0) for b in tip) - 1
            for _ in range(8):
                page = _get(f"https://mempool.space/api/v1/blocks/{height}")
                if not page or not isinstance(page, list):
                    break
                blocks.extend(page)
                height = min(b.get("height", 0) for b in page) - 1
                if len(blocks) >= 144:
                    break
    except Exception as e:
        log.debug(f"  block stats: {e}")

    if blocks:
        total_tx = sum(b.get("tx_count", 0) for b in blocks[:144])
        result["tx_count_24h"] = total_tx
        result["active_addr_proxy"] = f"~{total_tx:,} on-chain txs/24h"
        sizes = [b.get("size", 0) for b in blocks[:144] if b.get("size")]
        if sizes:
            result["avg_block_size_kb"] = round(sum(sizes) / len(sizes) / 1024, 1)
    return result


# ─── CoinGecko — market data + MVRV proxy ───────────────────────────────────

def fetch_coingecko_market() -> dict:
    result = {
        "market_cap_usd": "N/A", "realized_cap_usd": "N/A",
        "mvrv_ratio": "N/A", "btc_dominance": "N/A",
        "price_usd": "N/A", "price_7d_chg": "N/A",
        "timestamp": _TS(),
    }

    data = _get(
        "https://api.coingecko.com/api/v3/coins/bitcoin",
        params={"localization": "false", "tickers": "false",
                "community_data": "false", "developer_data": "false"},
    )
    if not data:
        return result

    md = data.get("market_data", {})
    result["price_usd"]      = md.get("current_price", {}).get("usd", "N/A")
    result["market_cap_usd"] = md.get("market_cap", {}).get("usd", "N/A")
    result["price_7d_chg"]   = md.get("price_change_percentage_7d", "N/A")

    result["mvrv_ratio"]     = "N/A (from CoinGlass onchain)"
    result["realized_cap_usd"] = "N/A"

    # BTC dominance from global endpoint
    gdata = _get("https://api.coingecko.com/api/v3/global")
    if gdata:
        pct = gdata.get("data", {}).get("market_cap_percentage", {})
        result["btc_dominance"] = round(pct.get("btc", 0), 2)

    return result


# ─── Active Addresses (blockchain.info) ─────────────────────────────────────

def fetch_active_addresses() -> dict:
    """
    Daily active addresses from blockchain.info/charts.
    Returns: {active_addr_today, active_addr_7d_avg, active_addr_30d_avg, trend_7d_pct, timestamp}
    """
    result = {"active_addr_today": "N/A", "active_addr_7d_avg": "N/A",
              "active_addr_30d_avg": "N/A", "active_addr_trend_7d_pct": "N/A",
              "timestamp": _TS()}
    data = _get("https://api.blockchain.info/charts/n-unique-addresses",
                params={"timespan": "30days", "format": "json", "sampled": "true"})
    if not data or "values" not in data:
        return result
    pts = data["values"]
    if not pts:
        return result
    vals = [p["y"] for p in pts if p.get("y")]
    if vals:
        result["active_addr_today"]    = int(vals[-1])
        result["active_addr_7d_avg"]   = int(sum(vals[-7:]) / min(len(vals), 7))
        result["active_addr_30d_avg"]  = int(sum(vals) / len(vals))
        if len(vals) >= 8:
            w0 = sum(vals[-7:]) / 7
            w1 = sum(vals[-14:-7]) / 7
            if w1:
                result["active_addr_trend_7d_pct"] = round((w0 - w1) / w1 * 100, 1)
    return result


# ─── Stablecoin Supply (DeFiLlama) ───────────────────────────────────────────

def fetch_stablecoin_supply() -> dict:
    """
    Total USDT + USDC circulating supply from DeFiLlama stablecoins API.
    Returns: {usdt_supply_b, usdc_supply_b, total_stable_b, ssr_proxy, timestamp}
    SSR proxy = BTC market cap / stablecoin supply (higher = less buying powder)
    """
    result = {"usdt_supply_b": "N/A", "usdc_supply_b": "N/A",
              "total_stable_b": "N/A", "ssr_proxy": "N/A", "timestamp": _TS()}
    data = _get("https://stablecoins.llama.fi/stablecoins?includePrices=true")
    if not data or "peggedAssets" not in data:
        return result
    assets = data["peggedAssets"]
    usdt = usdc = 0.0
    for a in assets:
        sym = a.get("symbol", "").upper()
        circ = a.get("circulating", {})
        usd_val = circ.get("peggedUSD", 0) or 0
        if sym == "USDT":
            usdt = float(usd_val)
        elif sym == "USDC":
            usdc = float(usd_val)
    total = usdt + usdc
    result["usdt_supply_b"] = round(usdt / 1e9, 2)
    result["usdc_supply_b"] = round(usdc / 1e9, 2)
    result["total_stable_b"] = round(total / 1e9, 2)
    return result


# ─── Exchange Reserve proxy via CoinGlass public endpoint ────────────────────

def fetch_exchange_reserve_from_output() -> dict:
    """
    Exchange reserves are inside OI stats data already captured.
    Parse from existing output files for trend.
    """
    result = {"exchange_reserve_btc": "N/A", "reserve_trend_30d": "N/A",
              "timestamp": _TS()}
    try:
        matches = sorted(Path("output").rglob("oi_stats_*.json"),
                         key=lambda p: p.stat().st_mtime)
        if not matches:
            return result
        with open(matches[-1], encoding="utf-8") as f:
            d = json.load(f)
        # OI stats contains exchange reserve data in some versions
        if isinstance(d, dict) and "exchangeReserve" in d:
            result["exchange_reserve_btc"] = d["exchangeReserve"]
    except Exception as e:
        log.debug(f"  reserve proxy: {e}")
    return result


# ─── ETF flows summary from cached farside data ──────────────────────────────

def parse_etf_flows_summary(etf_data: dict) -> dict:
    """
    Extract 7-day and 30-day net totals from the farside ETF data.
    etf_data: {headers, rows, last_30d_totals_m, fetched_at}
    """
    result = {
        "etf_net_7d_m": "N/A", "etf_net_30d_m": "N/A",
        "etf_top1_name": "N/A", "etf_top1_30d_m": "N/A",
        "etf_top2_name": "N/A", "etf_top2_30d_m": "N/A",
        "etf_top3_name": "N/A", "etf_top3_30d_m": "N/A",
        "etf_gbtc_30d_m": "N/A",
        "timestamp": _TS(),
    }
    if not etf_data or "last_30d_totals_m" not in etf_data:
        return result

    totals = etf_data["last_30d_totals_m"]
    rows   = etf_data.get("rows", [])

    def _to_f(s):
        if s in (None, "-", "", "N/A"):
            return 0.0
        try:
            return float(str(s).replace(",", "").replace("(", "-").replace(")", ""))
        except Exception:
            return 0.0

    # 30d net
    net_30d = sum(totals.values())
    result["etf_net_30d_m"] = round(net_30d, 1)

    # 7d net from last 7 rows
    headers = etf_data.get("headers", [])
    if headers and rows:
        last7 = rows[-7:]
        net7 = 0.0
        for row in last7:
            for col in headers[1:]:
                if col and col != "Total":
                    net7 += _to_f(row.get(col, "0"))
        result["etf_net_7d_m"] = round(net7, 1)

    # Top 3 by 30d inflows (excluding GBTC which often has outflows)
    GBTC_KEYS = {"GBTC"}
    inflows = {k: v for k, v in totals.items() if k not in GBTC_KEYS}
    sorted_etfs = sorted(inflows.items(), key=lambda x: x[1], reverse=True)
    for i, (name, val) in enumerate(sorted_etfs[:3]):
        result[f"etf_top{i+1}_name"]  = name
        result[f"etf_top{i+1}_30d_m"] = round(val, 1)
    result["etf_gbtc_30d_m"] = round(totals.get("GBTC", 0), 1)

    return result


# ─── Main orchestrator ───────────────────────────────────────────────────────

def fetch_all_onchain(etf_data: dict | None = None) -> dict:
    """
    Fetch all available public on-chain metrics.
    Returns a unified dict with timestamp on each sub-section.
    Caches result to output/onchain_cache.json.
    """
    log.info("Fetching on-chain data from public APIs...")

    result = {
        "fetched_at":     _TS(),
        "fear_greed":     fetch_fear_greed(),
        "mempool":        fetch_mempool_stats(),
        "hashrate":       fetch_hashrate(),
        "block_stats":    fetch_block_stats(),
        "market":         fetch_coingecko_market(),
        "active_addr":    fetch_active_addresses(),
        "stablecoins":    fetch_stablecoin_supply(),
        "exchange_res":   fetch_exchange_reserve_from_output(),
        "etf_summary":    parse_etf_flows_summary(etf_data or {}),
    }

    # CoinGlass on-chain metrics (SOPR, NUPL, MVRV, LTH/STH, Whales, Cohorts)
    if _HAS_COINGLASS:
        try:
            cg = _fetch_cg_onchain()
            result["coinglass_onchain"] = cg
            log.info(f"  CoinGlass on-chain merged: {list(cg.keys())}")
        except Exception as e:
            log.warning(f"  CoinGlass on-chain fetch failed (non-fatal): {e}")
            result["coinglass_onchain"] = {}
    else:
        result["coinglass_onchain"] = {}

    # Compute On-Chain Health Score from available signals
    score, weights_used = _compute_health_score(result)
    result["health_score"] = score
    result["health_score_weights"] = weights_used

    # Cache
    CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    log.info(f"  On-chain cache saved → {CACHE_FILE}")

    return result


def _compute_health_score(data: dict) -> tuple[dict, list]:
    """
    On-Chain Health Score. Weights per PDF spec:
    SOPR 15%, NUPL 15%, Exchange Reserves 15%, LTH Net Position 15%,
    Whale Activity 10%, MVRV 10%, Miner Flows 10%, ETF Flows 10%.
    Supplementary: Fear&Greed, Hashrate, BTC Dominance.
    """
    score_rows = []
    total = 0.0
    wsum  = 0.0
    cg = data.get("coinglass_onchain", {})

    def _add(metric, value, sig, weight, source="CoinGlass"):
        nonlocal total, wsum
        score_rows.append({"metric": metric, "value": value, "signal": sig,
                           "weight": weight, "source": source})
        total += sig * weight
        wsum  += weight

    def _na(metric, weight, note=""):
        score_rows.append({"metric": metric, "value": "N/A", "signal": 0,
                           "weight": weight, "source": note})

    # ── SOPR (15%) ──────────────────────────────────────────────────────────
    sopr = cg.get("sopr", "N/A")
    if sopr != "N/A":
        v = float(sopr)
        sig = 1 if v > 1.02 else (-1 if v < 0.98 else 0)
        _add(f"SOPR ({cg.get('sopr_signal','N/A')})", f"{v:.4f}", sig, 0.15)
    else:
        _na("SOPR", 0.15)

    # ── NUPL (15%) ──────────────────────────────────────────────────────────
    nupl = cg.get("nupl", "N/A")
    if nupl != "N/A":
        v = float(nupl)
        sig = 1 if v > 0.5 else (-1 if v < 0.25 else 0)
        _add(f"NUPL ({cg.get('nupl_label','N/A')})", f"{v:.4f}", sig, 0.15)
    else:
        _na("NUPL", 0.15)

    # ── MVRV (10%) ──────────────────────────────────────────────────────────
    mvrv = cg.get("mvrv", "N/A")
    if mvrv != "N/A":
        v = float(mvrv)
        sig = 1 if 1.0 < v < 3.5 else (-1 if v >= 3.5 else 0)
        _add(f"MVRV ({cg.get('mvrv_signal','N/A')})", f"{v:.3f}", sig, 0.10)
    else:
        _na("MVRV", 0.10)

    # ── LTH/STH Realized Price → distance signal (15%) ──────────────────────
    lth = cg.get("lth_price", "N/A")
    sth = cg.get("sth_price", "N/A")
    price = data.get("market", {}).get("price_usd", "N/A")
    if lth != "N/A" and price != "N/A":
        try:
            dist_lth = (float(price) - float(lth)) / float(lth) * 100
            sig = 1 if dist_lth > 0 else -1
            _add(f"Price vs LTH Realized", f"${lth:,.0f} ({dist_lth:+.1f}%)", sig, 0.15)
        except Exception:
            _na("LTH Net Position", 0.15)
    else:
        _na("LTH Net Position", 0.15)

    # ── Whale Activity (10%) ─────────────────────────────────────────────────
    whale_trend = cg.get("whale_addr_trend", "N/A")
    whale_count = cg.get("whale_addr_count", "N/A")
    if whale_trend != "N/A":
        sig = 1 if whale_trend == "Accumulating" else (-1 if whale_trend == "Distributing" else 0)
        _add(f"Whale Addrs >1000 BTC ({whale_trend})", str(whale_count), sig, 0.10)
    else:
        _na("Whale Activity", 0.10)

    # ── Exchange Reserves (15%) — placeholder, endpoint not yet captured ─────
    _na("Exchange Reserves", 0.15, "endpoint pending")

    # ── Miner Flows (10%) — placeholder ──────────────────────────────────────
    _na("Miner Flows", 0.10, "endpoint pending")

    # ── ETF Flows (10%) ───────────────────────────────────────────────────────
    etf_7d = data.get("etf_summary", {}).get("etf_net_7d_m", "N/A")
    if etf_7d != "N/A":
        sig = 1 if float(etf_7d) > 100 else (-1 if float(etf_7d) < -100 else 0)
        _add("ETF Flows 7d ($M)", f"${etf_7d}M", sig, 0.10, "Farside")
    else:
        _na("ETF Flows 7d", 0.10, "Farside")

    # ── Supplementary signals (unweighted in spec, added for context) ─────────
    fg_val = data.get("fear_greed", {}).get("fear_greed_current", "N/A")
    if fg_val != "N/A":
        fg = int(fg_val)
        sig = 1 if fg > 60 else (-1 if fg < 40 else 0)
        _add(f"Fear & Greed ({data['fear_greed'].get('fear_greed_label','')})",
             str(fg), sig, 0.05, "alternative.me")

    hr = data.get("hashrate", {}).get("hashrate_eh", "N/A")
    hr_1w = data.get("hashrate", {}).get("hashrate_1w_ago_eh", "N/A")
    if hr != "N/A" and hr_1w != "N/A":
        sig = 1 if float(hr) > float(hr_1w) else (-1 if float(hr) < float(hr_1w) * 0.99 else 0)
        _add("Hashrate trend 7d", f"{hr} EH/s", sig, 0.05, "mempool.space")

    available = sum(1 for r in score_rows if r["value"] != "N/A")
    normalized = round((total / wsum * 100) if wsum > 0 else 0, 1)
    label = "bullish" if normalized > 50 else ("bearish" if normalized < -20 else "neutral")
    return {
        "score": normalized, "label": label, "rows": score_rows,
        "note": f"{available}/{len(score_rows)} metrics available",
    }, score_rows


def load_cached() -> dict | None:
    """Load cached on-chain data if <2h old."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        ts_str = d.get("fetched_at", "")
        if ts_str:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
            age_h = (datetime.now(tz=timezone.utc) - dt).total_seconds() / 3600
            if age_h < 2:
                log.info(f"  Using cached on-chain data ({age_h:.1f}h old)")
                return d
    except Exception:
        pass
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import pathlib, json as _json

    # Load ETF flows from most recent output file
    etf_files = sorted(pathlib.Path("output").rglob("etf_flows_*.json"),
                       key=lambda p: p.stat().st_mtime)
    etf_data = None
    if etf_files:
        with open(etf_files[-1], encoding="utf-8") as f:
            etf_data = _json.load(f)
        print(f"ETF data loaded from {etf_files[-1]}")

    result = fetch_all_onchain(etf_data)
    hs = result["health_score"]
    print(f"\n=== On-Chain Health Score: {hs['score']} | {hs['label'].upper()} ===")
    print(f"    {hs['note']}")
    fg = result['fear_greed']
    hr = result['hashrate']
    mp = result['mempool']
    es = result['etf_summary']
    mk = result['market']
    print(f"Fear & Greed : {fg['fear_greed_current']} ({fg['fear_greed_label']})")
    print(f"Hashrate     : {hr['hashrate_eh']} EH/s  |  Next adj: {hr['next_adj_pct']}%  ({hr['blocks_until_adj']} blocks)")
    print(f"Mempool      : {mp['mempool_count']} txs  fee_mid={mp['fee_mid']} sat/vB")
    print(f"ETF 7d / 30d : {es['etf_net_7d_m']}M / {es['etf_net_30d_m']}M")
    print(f"BTC Dominance: {mk['btc_dominance']}%")
    aa = result['active_addr']
    sc = result['stablecoins']
    print(f"Active Addrs : {aa['active_addr_today']:,} today  7d avg: {aa['active_addr_7d_avg']:,}  trend: {aa['active_addr_trend_7d_pct']}%" if isinstance(aa['active_addr_today'], int) else f"Active Addrs : {aa['active_addr_today']}")
    print(f"Stablecoins  : USDT ${sc['usdt_supply_b']}B  USDC ${sc['usdc_supply_b']}B  Total ${sc['total_stable_b']}B")
    print(f"Cache file   : {CACHE_FILE}")
