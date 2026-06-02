from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


OUTPUT_DIR = Path("output")
HTML_NAME = "index.html"
DATA_JS_NAME = "dashboard_data.js"
MAX_LINE_POINTS = 240
MAX_BUBBLE_POINTS = 180
TIMESTAMP_RE = re.compile(r"^(?P<base>.+?)_(?P<stamp>\d{8}_\d{6})$")

TITLE_OVERRIDES = {
    "summary_metrics": "Summary Metrics Report",
    "heatmap_3d": "Liquidation Heatmap 3d Raw",
    "heatmap_7d": "Liquidation Heatmap 7d Raw",
    "raw_BTC": "Raw BTC Liquidation Heatmap",
    "oi_expiry": "Options OI By Expiry",
    "options_oi": "Options Open Interest",
    "options_vs_futures": "Options vs Futures",
    "options_greeks": "Options Greeks",
    "max_pain": "Options Max Pain",
    "delivery_volume": "Options Delivery Volume",
    "liq_heatmap_binance": "Binance Liquidation Heatmap Status",
    "liq_map_exchange": "Liquidation Map By Exchange",
    "liq_count_heatmap": "Liquidation Count Heatmap",
    "hyperliq_liqmap": "Hyperliquid Liquidation Map",
    "hyperliq_ratio": "Hyperliquid Trader Ratio",
    "oi_stats": "Open Interest Statistics",
    "oi_stats_altcoin": "Open Interest Statistics Altcoin",
    "oi_chart_v3": "Open Interest Chart V3",
    "oi_info": "Open Interest Snapshot",
    "vol_chart": "Futures Volume Chart",
    "orderbook_liquidity": "Orderbook Liquidity",
    "premium_index": "Premium Index",
    "coinbase_premium": "Coinbase Premium",
    "btc_dominance": "BTC Dominance",
    "funding_rate_history": "Funding Rate History",
    "insurance_fund": "Insurance Fund",
    "margin_rate": "Margin Rate",
    "liquidation_events": "Liquidation Events",
    "bitmex_funding_rate": "BitMEX Funding Rate",
}

ARRAY_LABEL_OVERRIDES = {
    "margin_rate": ["Margin Rate"],
    "premium_index": ["Metric 1", "Metric 2", "Metric 3", "Metric 4"],
    "coinbase_premium": ["Metric 1", "Metric 2", "Metric 3", "Metric 4", "Metric 5", "Metric 6"],
    "orderbook_liquidity": ["Metric 1", "Metric 2", "Metric 3", "Metric 4"],
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CoinGlass Output Dashboard</title>
  <style>
    :root {
      --bg: #f4f1e8;
      --bg-alt: #fbf8f1;
      --card: rgba(255, 255, 255, 0.88);
      --ink: #1f2a30;
      --muted: #5f6d72;
      --line: rgba(31, 42, 48, 0.12);
      --accent: #0f766e;
      --accent-2: #d97706;
      --accent-3: #2563eb;
      --shadow: 0 18px 45px rgba(31, 42, 48, 0.08);
      --radius: 24px;
      --radius-sm: 16px;
      --font-sans: "Aptos", "Segoe UI Variable Text", "Segoe UI", sans-serif;
      --font-mono: "Cascadia Code", "Consolas", monospace;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      font-family: var(--font-sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.08), transparent 34%),
        radial-gradient(circle at top right, rgba(217, 119, 6, 0.08), transparent 28%),
        linear-gradient(180deg, #f8f4eb 0%, #f1ede4 100%);
    }

    .page {
      width: min(1400px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 48px;
    }

    .hero {
      padding: 28px;
      background: linear-gradient(140deg, rgba(255,255,255,0.92), rgba(249,245,236,0.88));
      border: 1px solid rgba(31, 42, 48, 0.08);
      border-radius: 30px;
      box-shadow: var(--shadow);
      position: sticky;
      top: 16px;
      backdrop-filter: blur(12px);
      z-index: 3;
      margin-bottom: 26px;
    }

    .eyebrow {
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-weight: 700;
    }

    h1 {
      margin: 0 0 10px;
      font-size: clamp(30px, 5vw, 52px);
      line-height: 0.98;
      letter-spacing: -0.04em;
    }

    .hero p {
      margin: 0;
      color: var(--muted);
      max-width: 900px;
      font-size: 15px;
      line-height: 1.6;
    }

    .overview-grid,
    .stat-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      margin-top: 18px;
    }

    .overview-card,
    .stat-card {
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(31, 42, 48, 0.08);
      border-radius: var(--radius-sm);
      padding: 14px 16px;
      min-height: 84px;
    }

    .label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 8px;
      font-weight: 700;
    }

    .value {
      display: block;
      font-size: 22px;
      line-height: 1.1;
      letter-spacing: -0.03em;
      font-weight: 700;
    }

    .value.small {
      font-size: 16px;
      letter-spacing: 0;
      line-height: 1.35;
    }

    .dataset-list {
      display: grid;
      gap: 18px;
    }

    .dataset-card {
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(251,248,241,0.94));
      border: 1px solid rgba(31, 42, 48, 0.08);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 22px;
    }

    .dataset-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }

    .dataset-header h2 {
      margin: 0 0 8px;
      font-size: clamp(22px, 2.3vw, 30px);
      line-height: 1.05;
      letter-spacing: -0.03em;
    }

    .dataset-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(15, 118, 110, 0.08);
      color: #0f5b56;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }

    .dataset-desc {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
      max-width: 940px;
    }

    .notes {
      margin: 14px 0 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }

    .panel-grid {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      margin-top: 18px;
    }

    .panel {
      background: rgba(255,255,255,0.84);
      border: 1px solid rgba(31, 42, 48, 0.08);
      border-radius: 22px;
      padding: 16px;
      min-height: 220px;
      overflow: hidden;
    }

    .panel.wide {
      grid-column: 1 / -1;
    }

    .panel h3 {
      margin: 0 0 8px;
      font-size: 15px;
      letter-spacing: -0.01em;
    }

    .panel .note {
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }

    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
    }

    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }

    .legend-swatch {
      width: 12px;
      height: 12px;
      border-radius: 4px;
      flex: 0 0 auto;
    }

    svg.chart {
      width: 100%;
      height: auto;
      display: block;
      overflow: visible;
    }

    .axis-text,
    .grid-text {
      fill: #718086;
      font-size: 11px;
      font-family: var(--font-mono);
    }

    .grid-line {
      stroke: rgba(31, 42, 48, 0.08);
      stroke-width: 1;
    }

    .axis-line {
      stroke: rgba(31, 42, 48, 0.22);
      stroke-width: 1.1;
    }

    .series-line {
      fill: none;
      stroke-width: 2.2;
      stroke-linejoin: round;
      stroke-linecap: round;
    }

    .series-dot {
      stroke: white;
      stroke-width: 1.4;
    }

    .table-wrap {
      overflow-x: auto;
      border-radius: 16px;
      border: 1px solid rgba(31, 42, 48, 0.08);
      background: rgba(255,255,255,0.78);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }

    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(31, 42, 48, 0.08);
      text-align: left;
      white-space: nowrap;
    }

    th {
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    tr:last-child td {
      border-bottom: 0;
    }

    pre.message {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.6;
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--ink);
    }

    .empty-state {
      padding: 28px;
      border-radius: 24px;
      background: rgba(255,255,255,0.84);
      border: 1px solid rgba(31,42,48,0.08);
      box-shadow: var(--shadow);
      color: var(--muted);
    }

    @media (max-width: 820px) {
      .page {
        width: min(100vw - 20px, 1400px);
        padding-top: 14px;
      }

      .hero {
        position: static;
        padding: 22px;
      }

      .dataset-card,
      .panel {
        border-radius: 20px;
      }

      .dataset-header {
        flex-direction: column;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <p class="eyebrow">Output Dashboard</p>
      <h1>CoinGlass JSON Snapshot Explorer</h1>
      <p id="hero-summary">Loading dashboard data...</p>
      <div class="overview-grid" id="overview-grid"></div>
    </section>
    <main id="app"></main>
  </div>

  <script src="./dashboard_data.js"></script>
  <script>
    (() => {
      const palette = [
        "#0f766e", "#d97706", "#2563eb", "#be123c",
        "#059669", "#7c3aed", "#ea580c", "#0891b2",
        "#4f46e5", "#65a30d"
      ];

      function fmtNumber(value) {
        if (!Number.isFinite(value)) return "";
        const abs = Math.abs(value);
        if (abs >= 1e12) return (value / 1e12).toFixed(2) + "T";
        if (abs >= 1e9) return (value / 1e9).toFixed(2) + "B";
        if (abs >= 1e6) return (value / 1e6).toFixed(2) + "M";
        if (abs >= 1e3) return (value / 1e3).toFixed(2) + "K";
        if (abs >= 100) return value.toFixed(0);
        if (abs >= 1) return value.toFixed(2);
        if (abs === 0) return "0";
        return value.toFixed(4);
      }

      function fmtDate(ms) {
        if (!Number.isFinite(ms)) return "";
        return new Date(ms).toLocaleString();
      }

      function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
      }

      function appendLegend(container, items) {
        if (!items || !items.length) return;
        const legend = el("div", "legend");
        items.forEach((item) => {
          const entry = el("div", "legend-item");
          const swatch = el("span", "legend-swatch");
          swatch.style.background = item.color;
          entry.appendChild(swatch);
          entry.appendChild(el("span", "", item.label));
          legend.appendChild(entry);
        });
        container.appendChild(legend);
      }

      function linePath(points, scaleX, scaleY) {
        return points.map((point, index) => {
          const x = scaleX(point[0]);
          const y = scaleY(point[1]);
          return (index === 0 ? "M" : "L") + x.toFixed(2) + "," + y.toFixed(2);
        }).join(" ");
      }

      function createSvg(width, height) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "chart");
        svg.setAttribute("viewBox", "0 0 " + width + " " + height);
        svg.setAttribute("role", "img");
        return svg;
      }

      function svgNode(name, attrs) {
        const node = document.createElementNS("http://www.w3.org/2000/svg", name);
        Object.entries(attrs || {}).forEach(([key, value]) => {
          node.setAttribute(key, String(value));
        });
        return node;
      }

      function getTicks(min, max, count) {
        if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
        if (min === max) return [min];
        const step = (max - min) / Math.max(count - 1, 1);
        const ticks = [];
        for (let i = 0; i < count; i += 1) {
          ticks.push(min + step * i);
        }
        return ticks;
      }

      function yRange(values) {
        let min = Math.min(...values);
        let max = Math.max(...values);
        if (min === max) {
          const pad = min === 0 ? 1 : Math.abs(min) * 0.1;
          min -= pad;
          max += pad;
        }
        const span = max - min;
        const pad = span * 0.12;
        if (min >= 0) {
          min = Math.max(0, min - pad * 0.4);
        } else {
          min -= pad * 0.6;
        }
        max += pad;
        return [min, max];
      }

      function renderLine(panel) {
        const width = 780;
        const height = 310;
        const margin = { top: 14, right: 18, bottom: 48, left: 58 };
        const svg = createSvg(width, height);
        const plotW = width - margin.left - margin.right;
        const plotH = height - margin.top - margin.bottom;

        const categories = panel.xMode === "category"
          ? (panel.categories || panel.series[0].points.map((point) => point[0]))
          : null;

        const xValues = [];
        const yValues = [];
        panel.series.forEach((series) => {
          series.points.forEach((point) => {
            if (panel.xMode !== "category") xValues.push(point[0]);
            yValues.push(point[1]);
          });
        });

        const [yMin, yMax] = yRange(yValues);
        const scaleY = (value) => margin.top + plotH - ((value - yMin) / (yMax - yMin)) * plotH;

        let scaleX;
        let tickValues;
        if (panel.xMode === "category") {
          const denom = Math.max((categories.length || 1) - 1, 1);
          scaleX = (value) => {
            const index = categories.indexOf(value);
            return margin.left + (Math.max(index, 0) / denom) * plotW;
          };
          tickValues = categories;
        } else {
          const xMin = Math.min(...xValues);
          const xMax = Math.max(...xValues);
          scaleX = (value) => margin.left + ((value - xMin) / Math.max(xMax - xMin, 1)) * plotW;
          tickValues = getTicks(xMin, xMax, 5);
        }

        getTicks(yMin, yMax, 5).forEach((tick) => {
          const y = scaleY(tick);
          svg.appendChild(svgNode("line", {
            x1: margin.left,
            y1: y,
            x2: margin.left + plotW,
            y2: y,
            class: "grid-line"
          }));
          const text = svgNode("text", {
            x: margin.left - 10,
            y: y + 4,
            "text-anchor": "end",
            class: "grid-text"
          });
          text.textContent = fmtNumber(tick);
          svg.appendChild(text);
        });

        if (panel.xMode === "category") {
          const every = Math.max(1, Math.ceil(categories.length / 10));
          categories.forEach((value, index) => {
            if (index % every !== 0 && index !== categories.length - 1) return;
            const x = scaleX(value);
            const text = svgNode("text", {
              x,
              y: height - 16,
              "text-anchor": "middle",
              class: "axis-text"
            });
            text.textContent = value;
            svg.appendChild(text);
          });
        } else {
          tickValues.forEach((tick) => {
            const x = scaleX(tick);
            const text = svgNode("text", {
              x,
              y: height - 16,
              "text-anchor": "middle",
              class: "axis-text"
            });
            text.textContent = panel.xMode === "time" ? fmtDate(tick) : fmtNumber(tick);
            svg.appendChild(text);
          });
        }

        svg.appendChild(svgNode("line", {
          x1: margin.left,
          y1: margin.top + plotH,
          x2: margin.left + plotW,
          y2: margin.top + plotH,
          class: "axis-line"
        }));
        svg.appendChild(svgNode("line", {
          x1: margin.left,
          y1: margin.top,
          x2: margin.left,
          y2: margin.top + plotH,
          class: "axis-line"
        }));

        const legendItems = [];
        panel.series.forEach((series, index) => {
          const color = palette[index % palette.length];
          legendItems.push({ label: series.name, color });
          const path = svgNode("path", {
            d: linePath(series.points, scaleX, scaleY),
            stroke: color,
            class: "series-line"
          });
          svg.appendChild(path);
          if (series.points.length <= 60) {
            series.points.forEach((point) => {
              svg.appendChild(svgNode("circle", {
                cx: scaleX(point[0]),
                cy: scaleY(point[1]),
                r: 2.8,
                fill: color,
                class: "series-dot"
              }));
            });
          }
        });

        return { svg, legendItems };
      }

      function renderBar(panel) {
        const width = 780;
        const height = 310;
        const margin = { top: 14, right: 18, bottom: 56, left: 58 };
        const svg = createSvg(width, height);
        const plotW = width - margin.left - margin.right;
        const plotH = height - margin.top - margin.bottom;
        const values = [];
        panel.series.forEach((series) => values.push(...series.values));
        const [yMin, yMax] = yRange(values);
        const scaleY = (value) => margin.top + plotH - ((value - yMin) / (yMax - yMin)) * plotH;
        const band = plotW / Math.max(panel.categories.length, 1);
        const groupWidth = band * 0.74;
        const barWidth = groupWidth / Math.max(panel.series.length, 1);
        const legendItems = [];

        getTicks(yMin, yMax, 5).forEach((tick) => {
          const y = scaleY(tick);
          svg.appendChild(svgNode("line", {
            x1: margin.left,
            y1: y,
            x2: margin.left + plotW,
            y2: y,
            class: "grid-line"
          }));
          const text = svgNode("text", {
            x: margin.left - 10,
            y: y + 4,
            "text-anchor": "end",
            class: "grid-text"
          });
          text.textContent = fmtNumber(tick);
          svg.appendChild(text);
        });

        const zeroY = scaleY(0);
        svg.appendChild(svgNode("line", {
          x1: margin.left,
          y1: zeroY,
          x2: margin.left + plotW,
          y2: zeroY,
          class: "axis-line"
        }));
        svg.appendChild(svgNode("line", {
          x1: margin.left,
          y1: margin.top,
          x2: margin.left,
          y2: margin.top + plotH,
          class: "axis-line"
        }));

        panel.categories.forEach((category, catIndex) => {
          const xStart = margin.left + catIndex * band + (band - groupWidth) / 2;
          panel.series.forEach((series, seriesIndex) => {
            const value = series.values[catIndex] || 0;
            const color = palette[seriesIndex % palette.length];
            const x = xStart + seriesIndex * barWidth;
            const y = value >= 0 ? scaleY(value) : zeroY;
            const h = Math.abs(scaleY(value) - zeroY);
            svg.appendChild(svgNode("rect", {
              x,
              y,
              width: Math.max(barWidth - 2, 3),
              height: Math.max(h, 1),
              rx: 4,
              fill: color,
              opacity: 0.88
            }));
          });

          const label = svgNode("text", {
            x: margin.left + catIndex * band + band / 2,
            y: height - 16,
            "text-anchor": "middle",
            class: "axis-text"
          });
          label.textContent = category;
          svg.appendChild(label);
        });

        panel.series.forEach((series, index) => {
          legendItems.push({ label: series.name, color: palette[index % palette.length] });
        });

        return { svg, legendItems };
      }

      function renderBubble(panel) {
        const width = 780;
        const height = 320;
        const margin = { top: 14, right: 18, bottom: 48, left: 58 };
        const svg = createSvg(width, height);
        const plotW = width - margin.left - margin.right;
        const plotH = height - margin.top - margin.bottom;
        const xValues = panel.points.map((point) => point.x);
        const yValues = panel.points.map((point) => point.y);
        const sizeValues = panel.points.map((point) => point.size);
        const xMin = Math.min(...xValues);
        const xMax = Math.max(...xValues);
        const [yMin, yMax] = yRange(yValues);
        const sizeMin = Math.min(...sizeValues);
        const sizeMax = Math.max(...sizeValues);
        const scaleX = (value) => margin.left + ((value - xMin) / Math.max(xMax - xMin, 1)) * plotW;
        const scaleY = (value) => margin.top + plotH - ((value - yMin) / (yMax - yMin)) * plotH;
        const scaleR = (value) => {
          if (sizeMin === sizeMax) return 8;
          return 4 + ((value - sizeMin) / (sizeMax - sizeMin)) * 14;
        };
        const groups = [...new Set(panel.points.map((point) => point.group || "Series"))];
        const legendItems = groups.map((group, index) => ({
          label: group,
          color: palette[index % palette.length]
        }));

        getTicks(yMin, yMax, 5).forEach((tick) => {
          const y = scaleY(tick);
          svg.appendChild(svgNode("line", {
            x1: margin.left,
            y1: y,
            x2: margin.left + plotW,
            y2: y,
            class: "grid-line"
          }));
          const text = svgNode("text", {
            x: margin.left - 10,
            y: y + 4,
            "text-anchor": "end",
            class: "grid-text"
          });
          text.textContent = fmtNumber(tick);
          svg.appendChild(text);
        });

        getTicks(xMin, xMax, 5).forEach((tick) => {
          const x = scaleX(tick);
          const text = svgNode("text", {
            x,
            y: height - 16,
            "text-anchor": "middle",
            class: "axis-text"
          });
          text.textContent = panel.xMode === "time" ? fmtDate(tick) : fmtNumber(tick);
          svg.appendChild(text);
        });

        svg.appendChild(svgNode("line", {
          x1: margin.left,
          y1: margin.top + plotH,
          x2: margin.left + plotW,
          y2: margin.top + plotH,
          class: "axis-line"
        }));
        svg.appendChild(svgNode("line", {
          x1: margin.left,
          y1: margin.top,
          x2: margin.left,
          y2: margin.top + plotH,
          class: "axis-line"
        }));

        panel.points.forEach((point) => {
          const color = palette[groups.indexOf(point.group || "Series") % palette.length];
          svg.appendChild(svgNode("circle", {
            cx: scaleX(point.x),
            cy: scaleY(point.y),
            r: scaleR(point.size),
            fill: color,
            opacity: 0.55,
            stroke: color,
            "stroke-width": 1.4
          }));
        });

        return { svg, legendItems };
      }

      function renderTable(panel) {
        const wrap = el("div", "table-wrap");
        const table = el("table");
        const thead = el("thead");
        const headerRow = el("tr");
        panel.columns.forEach((column) => headerRow.appendChild(el("th", "", column)));
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = el("tbody");
        panel.rows.forEach((row) => {
          const tr = el("tr");
          row.forEach((cell) => tr.appendChild(el("td", "", cell)));
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        return wrap;
      }

      function panelNode(panel, index) {
        const node = el("section", "panel" + (panel.wide ? " wide" : ""));
        node.appendChild(el("h3", "", panel.title));

        if (panel.type === "line") {
          const result = renderLine(panel);
          node.appendChild(result.svg);
          appendLegend(node, result.legendItems);
        } else if (panel.type === "bar") {
          const result = renderBar(panel);
          node.appendChild(result.svg);
          appendLegend(node, result.legendItems);
        } else if (panel.type === "bubble") {
          const result = renderBubble(panel);
          node.appendChild(result.svg);
          appendLegend(node, result.legendItems);
        } else if (panel.type === "table") {
          node.appendChild(renderTable(panel));
        } else {
          const pre = el("pre", "message");
          pre.textContent = panel.text || "";
          node.appendChild(pre);
        }

        if (panel.note) {
          node.appendChild(el("p", "note", panel.note));
        }

        return node;
      }

      function datasetNode(dataset) {
        const card = el("section", "dataset-card");

        const header = el("div", "dataset-header");
        const titleWrap = el("div");
        titleWrap.appendChild(el("h2", "", dataset.title));
        if (dataset.description) {
          titleWrap.appendChild(el("p", "dataset-desc", dataset.description));
        }
        header.appendChild(titleWrap);

        const meta = el("div", "dataset-meta");
        meta.appendChild(el("span", "badge", dataset.sourceFile));
        meta.appendChild(el("span", "badge", dataset.snapshotLabel));
        if (dataset.snapshotCount > 1) {
          meta.appendChild(el("span", "badge", "Latest of " + dataset.snapshotCount + " snapshots"));
        }
        header.appendChild(meta);
        card.appendChild(header);

        const statGrid = el("div", "stat-grid");
        dataset.stats.forEach((item) => {
          const box = el("div", "stat-card");
          box.appendChild(el("span", "label", item.label));
          const value = el("span", "value" + ((item.value || "").length > 18 ? " small" : ""), item.value);
          box.appendChild(value);
          statGrid.appendChild(box);
        });
        card.appendChild(statGrid);

        if (dataset.notes && dataset.notes.length) {
          const notes = el("ul", "notes");
          dataset.notes.forEach((note) => notes.appendChild(el("li", "", note)));
          card.appendChild(notes);
        }

        const grid = el("div", "panel-grid");
        dataset.panels.forEach((panel, index) => grid.appendChild(panelNode(panel, index)));
        card.appendChild(grid);
        return card;
      }

      function renderDashboard(payload) {
        const app = document.getElementById("app");
        const overviewGrid = document.getElementById("overview-grid");
        const summary = document.getElementById("hero-summary");

        if (!payload || !payload.datasets || !payload.datasets.length) {
          summary.textContent = "No datasets were found in the output folder.";
          const empty = el("section", "empty-state");
          empty.textContent = "Run the scraper or place JSON files in the output folder, then rebuild the dashboard.";
          app.appendChild(empty);
          return;
        }

        summary.textContent = payload.summary;
        payload.overview.forEach((item) => {
          const box = el("div", "overview-card");
          box.appendChild(el("span", "label", item.label));
          const value = el("span", "value" + ((item.value || "").length > 18 ? " small" : ""), item.value);
          box.appendChild(value);
          overviewGrid.appendChild(box);
        });

        const list = el("div", "dataset-list");
        payload.datasets.forEach((dataset) => list.appendChild(datasetNode(dataset)));
        app.appendChild(list);
      }

      renderDashboard(window.DASHBOARD_DATA || null);
    })();
  </script>
</body>
</html>
"""


def split_dataset_name(path: Path) -> tuple[str, datetime | None]:
    match = TIMESTAMP_RE.match(path.stem)
    if not match:
        return path.stem, None
    stamp = match.group("stamp")
    try:
        return match.group("base"), datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    except ValueError:
        return match.group("base"), None


def humanize_slug(slug: str) -> str:
    if slug in TITLE_OVERRIDES:
        return TITLE_OVERRIDES[slug]
    parts = slug.replace("-", "_").split("_")
    return " ".join(part.upper() if len(part) <= 3 else part.capitalize() for part in parts)


def humanize_key(key: str) -> str:
    key = key.replace("Radio", "Ratio").replace("Usd", "USD").replace("Oi", "OI")
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    key = key.replace("_", " ").strip()
    return " ".join(word.upper() if word.upper() in {"BTC", "ETH", "USD", "OI"} else word.capitalize() for word in key.split())


def as_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            return float(value)
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def normalize_timestamp(value) -> int | None:
    number = as_float(value)
    if number is None:
        return None
    integer = int(number)
    if 946684800000 <= integer <= 4102444800000:
        return integer
    if 946684800 <= integer <= 4102444800:
        return integer * 1000
    return None


def infer_x_mode(values: list) -> tuple[str, list]:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return "category", ["" for _ in values]

    timestamp_hits = sum(normalize_timestamp(value) is not None for value in non_null)
    if timestamp_hits >= max(3, math.ceil(len(non_null) * 0.7)):
        return "time", [normalize_timestamp(value) for value in values]

    numeric_hits = sum(as_float(value) is not None for value in non_null)
    if numeric_hits == len(non_null):
        return "number", [as_float(value) for value in values]

    return "category", ["" if value is None else str(value) for value in values]


def sample_indices(length: int, max_points: int) -> list[int]:
    if length <= max_points:
        return list(range(length))
    if max_points <= 1:
        return [length - 1]
    indices = {0, length - 1}
    for step in range(1, max_points - 1):
        idx = int(round(step * (length - 1) / (max_points - 1)))
        indices.add(idx)
    return sorted(indices)


def human_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if value >= 100 or unit == "B":
        return f"{value:.0f} {unit}"
    return f"{value:.1f} {unit}"


def pretty_number(value) -> str:
    number = as_float(value)
    if number is None:
        return "n/a"
    abs_value = abs(number)
    if abs_value >= 1e12:
        return f"{number / 1e12:.2f}T"
    if abs_value >= 1e9:
        return f"{number / 1e9:.2f}B"
    if abs_value >= 1e6:
        return f"{number / 1e6:.2f}M"
    if abs_value >= 1e3:
        return f"{number / 1e3:.2f}K"
    if abs_value >= 100:
        return f"{number:.0f}"
    if abs_value >= 1:
        return f"{number:.2f}"
    if number == 0:
        return "0"
    return f"{number:.4f}"


def pretty_range(low, high) -> str:
    return f"{pretty_number(low)} -> {pretty_number(high)}"


def format_snapshot(dt: datetime | None) -> str:
    if dt is None:
        return "Snapshot unknown"
    return dt.strftime("Snapshot %Y-%m-%d %H:%M:%S")


def short_text(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def note_join(*parts: str) -> str | None:
    items = [part for part in parts if part]
    return " ".join(items) if items else None


def make_line_panel(title: str, x_values: list, series_map: dict[str, list], max_points: int = MAX_LINE_POINTS, max_series: int | None = None, note: str | None = None, wide: bool = False) -> dict | None:
    if not x_values or not series_map:
        return None
    x_mode, coerced_x = infer_x_mode(x_values)
    ordered_names = list(series_map.keys())
    if max_series and len(ordered_names) > max_series:
        scored = sorted(
            ordered_names,
            key=lambda name: max((abs(as_float(value) or 0.0) for value in series_map[name]), default=0.0),
            reverse=True,
        )
        ordered_names = scored[:max_series]
        note = note_join(note, f"Showing the {len(ordered_names)} highest-magnitude series.")

    indices = sample_indices(len(coerced_x), max_points)
    if len(coerced_x) > max_points:
        note = note_join(note, f"Downsampled from {len(coerced_x)} to {len(indices)} points per series.")

    series = []
    categories = []
    for name in ordered_names:
        y_values = series_map.get(name, [])
        points = []
        for idx in indices:
            if idx >= len(y_values) or idx >= len(coerced_x):
                continue
            x_value = coerced_x[idx]
            y_value = as_float(y_values[idx])
            if x_value is None or y_value is None:
                continue
            points.append([x_value if x_mode != "category" else str(x_value), y_value])
        if points:
            series.append({"name": name, "points": points})
            if x_mode == "category":
                categories = [point[0] for point in points]

    if not series:
        return None

    panel = {
        "type": "line",
        "title": title,
        "xMode": x_mode,
        "series": series,
        "note": note,
        "wide": wide,
    }
    if x_mode == "category":
        panel["categories"] = categories
    return panel


def make_bar_panel(title: str, categories: list[str], series_map: dict[str, list], note: str | None = None, wide: bool = False) -> dict | None:
    if not categories or not series_map:
        return None
    series = []
    for name, values in series_map.items():
        normalized = [(as_float(value) or 0.0) for value in values[: len(categories)]]
        if any(value != 0 for value in normalized):
            series.append({"name": name, "values": normalized})
    if not series:
        return None
    return {
        "type": "bar",
        "title": title,
        "categories": [str(category) for category in categories],
        "series": series,
        "note": note,
        "wide": wide,
    }


def make_bubble_panel(title: str, points: list[dict], x_mode: str = "number", note: str | None = None, wide: bool = False) -> dict | None:
    if not points:
        return None
    trimmed = sorted(points, key=lambda item: item["size"], reverse=True)[:MAX_BUBBLE_POINTS]
    if len(points) > len(trimmed):
        note = note_join(note, f"Showing the {len(trimmed)} largest points.")
    return {
        "type": "bubble",
        "title": title,
        "xMode": x_mode,
        "points": trimmed,
        "note": note,
        "wide": wide,
    }


def make_table_panel(title: str, columns: list[str], rows: list[list[str]], note: str | None = None, wide: bool = False) -> dict:
    return {
        "type": "table",
        "title": title,
        "columns": columns,
        "rows": rows,
        "note": note,
        "wide": wide,
    }


def make_message_panel(title: str, text: str, wide: bool = False) -> dict:
    return {
        "type": "message",
        "title": title,
        "text": text,
        "wide": wide,
    }


def dataset_shell(base: str, source_path: Path, snapshot: datetime | None, snapshot_count: int, description: str) -> dict:
    return {
        "id": base,
        "title": humanize_slug(base),
        "sourceFile": source_path.name,
        "snapshotLabel": format_snapshot(snapshot),
        "snapshotCount": snapshot_count,
        "description": description,
        "stats": [],
        "notes": [],
        "panels": [],
    }


def collect_latest_sources(output_dir: Path) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    scan_paths = list(output_dir.glob("*.json"))
    for subdir in output_dir.iterdir():
        if subdir.is_dir():
            scan_paths.extend(subdir.glob("*.json"))
    for path in scan_paths:
        if path.name.startswith("dashboard_"):
            continue
        base, snapshot = split_dataset_name(path)
        groups[base].append({"path": path, "snapshot": snapshot})

    latest = []
    for base, items in groups.items():
        items.sort(key=lambda item: (item["snapshot"] or datetime.min, item["path"].stat().st_mtime), reverse=True)
        latest.append(
            {
                "base": base,
                "path": items[0]["path"],
                "snapshot": items[0]["snapshot"],
                "snapshot_count": len(items),
            }
        )
    latest.sort(key=lambda item: item["base"])
    return latest


def group_series_by_magnitude(labels: list[str], columns: list[list]) -> list[tuple[list[str], list[list]]]:
    scored = []
    for label, values in zip(labels, columns):
        numeric_values = [abs(as_float(value) or 0.0) for value in values if as_float(value) is not None]
        median = sorted(numeric_values)[len(numeric_values) // 2] if numeric_values else 0.0
        scored.append((label, values, median))
    scored.sort(key=lambda item: item[2])
    groups = []
    current = []
    current_values = []
    previous = None
    for label, values, median in scored:
        if previous is not None and median > 0 and previous > 0 and median / previous > 500:
            groups.append((current, current_values))
            current, current_values = [], []
        current.append(label)
        current_values.append(values)
        previous = max(median, 1e-12)
    if current:
        groups.append((current, current_values))
    return groups


def build_array_timeseries_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Rendered from an unlabeled array-style time series. Series names follow source order when the API did not provide labels.",
    )
    first_row = payload[0]
    labels = ARRAY_LABEL_OVERRIDES.get(base, [f"Metric {index + 1}" for index in range(max(len(first_row) - 1, 0))])
    columns = [[] for _ in labels]
    x_values = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 2:
            continue
        x_values.append(row[0])
        for index, label in enumerate(labels):
            columns[index].append(row[index + 1] if index + 1 < len(row) else None)

    groups = group_series_by_magnitude(labels, columns)
    for idx, (group_labels, group_columns) in enumerate(groups, start=1):
        title = "Series Overview" if len(groups) == 1 else f"Series Overview {idx}"
        panel = make_line_panel(
            title,
            x_values,
            {label: values for label, values in zip(group_labels, group_columns)},
            note="Array columns did not include field names, so the dashboard keeps their source order.",
            wide=True if idx == 1 else False,
        )
        if panel:
            dataset["panels"].append(panel)

    latest_values = []
    for label, values in zip(labels, columns):
        numeric_values = [as_float(value) for value in values if as_float(value) is not None]
        if numeric_values:
            latest_values.append(f"{label}: {pretty_number(numeric_values[-1])}")

    dataset["stats"] = [
        {"label": "Rows", "value": str(len(payload))},
        {"label": "Series", "value": str(len(labels))},
        {"label": "Latest Values", "value": "; ".join(latest_values[:3]) or "n/a"},
        {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
    ]
    return dataset


def build_map_timeseries_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Multi-series time history built from the latest snapshot for this dataset.",
    )

    date_list = payload.get("dateList") or payload.get("timeList") or []
    if payload.get("dataMap"):
        panel = make_line_panel(
            "Primary Series",
            date_list,
            {name: values for name, values in payload["dataMap"].items()},
            max_series=8,
            note="Largest series are prioritized when the source includes many exchanges.",
            wide=True,
        )
        if panel:
            dataset["panels"].append(panel)

    fr_map = payload.get("frDataMap")
    if isinstance(fr_map, dict):
        panel = make_line_panel(
            "Funding Rate Series",
            date_list,
            {name: values for name, values in fr_map.items()},
            max_series=8,
        )
        if panel:
            dataset["panels"].append(panel)

    price_list = payload.get("priceList")
    if isinstance(price_list, list):
        panel = make_line_panel("Reference Price", date_list, {"Price": price_list})
        if panel:
            dataset["panels"].append(panel)

    dataset["stats"] = [
        {"label": "Points", "value": str(len(date_list))},
        {"label": "Series", "value": str(len((payload.get("dataMap") or {}).keys()))},
        {"label": "Latest Price", "value": pretty_number(price_list[-1]) if isinstance(price_list, list) and price_list else "n/a"},
        {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
    ]
    return dataset


def build_simple_lists_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Single-dataset time history with separate series for the main numeric lists in the JSON file.",
    )
    x_values = payload.get("dateList") or []
    ordered_fields = [key for key in ["openInterestList", "priceList", "volUsdList"] if isinstance(payload.get(key), list)]
    for field in ordered_fields:
        panel = make_line_panel(humanize_key(field), x_values, {humanize_key(field): payload[field]}, wide=(field == ordered_fields[0]))
        if panel:
            dataset["panels"].append(panel)

    dataset["stats"] = [
        {"label": "Points", "value": str(len(x_values))},
        {"label": "Latest OI", "value": pretty_number((payload.get("openInterestList") or [None])[-1])},
        {"label": "Latest Price", "value": pretty_number((payload.get("priceList") or [None])[-1])},
        {"label": "Latest Volume", "value": pretty_number((payload.get("volUsdList") or [None])[-1])},
    ]
    return dataset


def build_options_greeks_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Strike-based options greeks curves from the current snapshot.",
    )
    for greek in ["delta", "gamma", "theta", "vega"]:
        greek_payload = payload.get(greek)
        if not isinstance(greek_payload, dict):
            continue
        panel = make_line_panel(
            humanize_key(greek),
            greek_payload.get("strikePriceList") or [],
            {humanize_key(greek): greek_payload.get("valueList") or []},
            wide=(greek == "delta"),
        )
        if panel:
            dataset["panels"].append(panel)

    dataset["stats"] = [
        {"label": "Expiries", "value": str(len(payload.get("keys") or []))},
        {"label": "Strikes", "value": str(len((payload.get("delta") or {}).get("strikePriceList") or []))},
        {"label": "Latest Expiry", "value": (payload.get("keys") or ["n/a"])[0]},
        {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
    ]
    return dataset


def build_expiry_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Grouped by expiry code, using the latest totals and lists available in the file.",
    )
    inner = payload.get("data") or {}
    categories = inner.get("keyList") or payload.get("keys") or []
    if not categories:
        categories = [f"Bucket {index + 1}" for index in range(len(inner.get("callOiList") or []))]

    panel = make_bar_panel(
        "Open Interest By Expiry",
        categories,
        {
            "Call OI": inner.get("callOiList") or [],
            "Put OI": inner.get("putOiList") or [],
        },
        wide=True,
    )
    if panel:
        dataset["panels"].append(panel)

    panel = make_bar_panel(
        "Volume By Expiry",
        categories,
        {
            "Call Volume": inner.get("callVolList") or [],
            "Put Volume": inner.get("putVolList") or [],
        },
    )
    if panel:
        dataset["panels"].append(panel)

    if inner.get("notionalOiList"):
        panel = make_line_panel(
            "Notional Open Interest",
            categories,
            {"Notional OI": inner.get("notionalOiList") or []},
        )
        if panel:
            dataset["panels"].append(panel)

    dataset["stats"] = [
        {"label": "Expiries", "value": str(len(categories))},
        {"label": "Call OI", "value": pretty_number(inner.get("callOi"))},
        {"label": "Put OI", "value": pretty_number(inner.get("putOi"))},
        {"label": "Call / Put Vol", "value": f"{pretty_number(inner.get('callVol'))} / {pretty_number(inner.get('putVol'))}"},
    ]
    return dataset


def build_options_vs_futures_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Comparative time series between the options and futures related metrics returned by the source.",
    )
    x_values = payload.get("timeList") or []
    panel = make_line_panel(
        "BTC vs ETH Series",
        x_values,
        {
            "BTC": payload.get("btc") or [],
            "ETH": payload.get("eth") or [],
        },
        wide=True,
    )
    if panel:
        dataset["panels"].append(panel)

    panel = make_line_panel("BTC Price", x_values, {"BTC Price": payload.get("btcPrice") or []})
    if panel:
        dataset["panels"].append(panel)

    dataset["stats"] = [
        {"label": "Points", "value": str(len(x_values))},
        {"label": "Latest BTC", "value": pretty_number((payload.get("btc") or [None])[-1])},
        {"label": "Latest ETH", "value": pretty_number((payload.get("eth") or [None])[-1])},
        {"label": "Latest Price", "value": pretty_number((payload.get("btcPrice") or [None])[-1])},
    ]
    return dataset


def build_max_pain_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Expiry snapshot showing call and put OI alongside the max pain level.",
    )
    categories = [str(item.get("time", f"Bucket {index + 1}")) for index, item in enumerate(payload)]
    panel = make_bar_panel(
        "Call vs Put OI",
        categories,
        {
            "Call OI": [item.get("callOi") for item in payload],
            "Put OI": [item.get("putOi") for item in payload],
        },
        wide=True,
    )
    if panel:
        dataset["panels"].append(panel)

    panel = make_line_panel(
        "Max Pain",
        categories,
        {"Max Pain": [item.get("maxPain") for item in payload]},
    )
    if panel:
        dataset["panels"].append(panel)

    dataset["stats"] = [
        {"label": "Expiries", "value": str(len(payload))},
        {"label": "Largest Call OI", "value": pretty_number(max((as_float(item.get("callOi")) or 0.0 for item in payload), default=0.0))},
        {"label": "Largest Put OI", "value": pretty_number(max((as_float(item.get("putOi")) or 0.0 for item in payload), default=0.0))},
        {"label": "Latest Max Pain", "value": pretty_number((payload[-1] if payload else {}).get("maxPain"))},
    ]
    return dataset


def build_liq_count_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Time history of liquidation counts across symbols, with the busiest symbols highlighted.",
    )
    scored = []
    for item in payload:
        points = item.get("list") or []
        total = sum((as_float(row[1]) or 0.0 for row in points if isinstance(row, list) and len(row) >= 2))
        latest = as_float(points[-1][1]) if points else 0.0
        scored.append((item.get("symbol", "Unknown"), total, latest, points))
    scored.sort(key=lambda row: (row[2], row[1]), reverse=True)
    top = scored[:8]

    x_values = [row[0] for row in top[0][3]] if top else []
    series_map = {symbol: [entry[1] for entry in points] for symbol, _total, _latest, points in top}
    panel = make_line_panel("Top Symbols", x_values, series_map, max_series=8, wide=True)
    if panel:
        dataset["panels"].append(panel)

    rows = [[symbol, pretty_number(total), pretty_number(latest)] for symbol, total, latest, _points in scored[:12]]
    dataset["panels"].append(make_table_panel("Symbol Summary", ["Symbol", "Total Count", "Latest Count"], rows))

    dataset["stats"] = [
        {"label": "Symbols", "value": str(len(payload))},
        {"label": "Highlighted", "value": str(len(top))},
        {"label": "Rows / Symbol", "value": str(len(x_values))},
        {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
    ]
    return dataset


def build_hyperliq_ratio_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Hyperliquid trader-ratio time series from the latest JSON snapshot.",
    )
    keys = ["longUserSize", "shortUserSize", "userSize"]
    panel = make_line_panel(
        "Trader Ratio Series",
        [item.get("dateTime") for item in payload],
        {humanize_key(key): [entry.get(key) for entry in payload] for key in keys},
        wide=True,
    )
    if panel:
        dataset["panels"].append(panel)

    latest = payload[-1] if payload else {}
    dataset["stats"] = [
        {"label": "Points", "value": str(len(payload))},
        {"label": "Long Users", "value": pretty_number(latest.get("longUserSize"))},
        {"label": "Short Users", "value": pretty_number(latest.get("shortUserSize"))},
        {"label": "Total Users", "value": pretty_number(latest.get("userSize"))},
    ]
    return dataset


def build_object_timeseries_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int, time_key: str) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Time-series object array rendered directly from the numeric fields in the source file.",
    )
    if not payload:
        dataset["panels"].append(make_message_panel("No Data", "The JSON array is empty."))
        dataset["stats"] = [{"label": "Rows", "value": "0"}]
        return dataset

    first = payload[0]
    numeric_keys = []
    for key in first.keys():
        if key == time_key:
            continue
        if any(as_float(item.get(key)) is not None for item in payload[: min(len(payload), 40)]):
            numeric_keys.append(key)

    panel = make_line_panel(
        "Primary Series",
        [item.get(time_key) for item in payload],
        {humanize_key(key): [entry.get(key) for entry in payload] for key in numeric_keys[:8]},
        wide=True,
    )
    if panel:
        dataset["panels"].append(panel)

    latest = payload[-1]
    stats = [{"label": "Rows", "value": str(len(payload))}]
    for key in numeric_keys[:3]:
        stats.append({"label": humanize_key(key), "value": pretty_number(latest.get(key))})
    dataset["stats"] = stats[:4]
    return dataset


def build_oi_info_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Exchange-level open-interest snapshot sorted by the largest open interest values.",
    )
    sorted_rows = sorted(payload, key=lambda row: as_float(row.get("openInterest")) or 0.0, reverse=True)
    top = sorted_rows[:10]
    categories = [row.get("exchangeName", f"Exchange {index + 1}") for index, row in enumerate(top)]

    panel = make_bar_panel(
        "Open Interest By Exchange",
        categories,
        {"Open Interest": [row.get("openInterest") for row in top]},
        wide=True,
    )
    if panel:
        dataset["panels"].append(panel)

    panel = make_bar_panel(
        "Volume USD By Exchange",
        categories,
        {"Volume USD": [row.get("volUsd") for row in top]},
    )
    if panel:
        dataset["panels"].append(panel)

    table_rows = [
        [
            row.get("exchangeName", "n/a"),
            pretty_number(row.get("openInterest")),
            pretty_number(row.get("volUsd")),
            pretty_number(row.get("oiVolRadio")),
            pretty_number(row.get("h24Change")),
        ]
        for row in top
    ]
    dataset["panels"].append(
        make_table_panel("Top Exchanges", ["Exchange", "Open Interest", "Volume USD", "OI/Vol Ratio", "24h Change"], table_rows)
    )

    total_oi = sum((as_float(row.get("openInterest")) or 0.0) for row in payload)
    total_vol = sum((as_float(row.get("volUsd")) or 0.0) for row in payload)
    dataset["stats"] = [
        {"label": "Rows", "value": str(len(payload))},
        {"label": "Total OI", "value": pretty_number(total_oi)},
        {"label": "Total Volume", "value": pretty_number(total_vol)},
        {"label": "Top Exchange", "value": top[0].get("exchangeName", "n/a") if top else "n/a"},
    ]
    return dataset


def build_insurance_fund_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Asset-level insurance fund balances over time, focused on the largest current balances.",
    )
    grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for row in payload:
        asset = row.get("asset", "Unknown")
        ts = normalize_timestamp(row.get("createTime"))
        balance = as_float(row.get("balance"))
        if ts is None or balance is None:
            continue
        grouped[asset].append((ts, balance))

    latest_balances = []
    for asset, points in grouped.items():
        points.sort(key=lambda item: item[0])
        latest_balances.append((asset, points[-1][1], points))
    latest_balances.sort(key=lambda item: item[1], reverse=True)
    top_assets = latest_balances[:6]

    if top_assets:
        x_values = [point[0] for point in top_assets[0][2]]
        series_map = {asset: [value for _ts, value in points] for asset, _latest, points in top_assets}
        panel = make_line_panel("Top Asset Balances", x_values, series_map, wide=True)
        if panel:
            dataset["panels"].append(panel)

        panel = make_bar_panel(
            "Latest Balances",
            [asset for asset, _latest, _points in latest_balances[:10]],
            {"Balance": [latest for _asset, latest, _points in latest_balances[:10]]},
        )
        if panel:
            dataset["panels"].append(panel)

    rows = [[asset, pretty_number(balance)] for asset, balance, _points in latest_balances[:12]]
    dataset["panels"].append(make_table_panel("Asset Snapshot", ["Asset", "Latest Balance"], rows))

    dataset["stats"] = [
        {"label": "Assets", "value": str(len(grouped))},
        {"label": "Rows", "value": str(len(payload))},
        {"label": "Largest Balance", "value": pretty_number(latest_balances[0][1]) if latest_balances else "n/a"},
        {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
    ]
    return dataset


def build_btc_dominance_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Dominance mix over time across BTC, ETH, SOL, BNB, USDT, and other categories.",
    )
    keys = [key for key in payload[0].keys() if key != "timestamp"] if payload else []
    panel = make_line_panel(
        "Dominance Mix",
        [item.get("timestamp") for item in payload],
        {humanize_key(key): [entry.get(key) for entry in payload] for key in keys},
        wide=True,
    )
    if panel:
        dataset["panels"].append(panel)

    latest = payload[-1] if payload else {}
    dataset["stats"] = [{"label": "Rows", "value": str(len(payload))}]
    for key in keys[:3]:
        dataset["stats"].append({"label": humanize_key(key), "value": pretty_number(latest.get(key))})
    return dataset


def build_raw_heatmap_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Coordinate-style liquidation heatmap reduced into a volume timeline and the strongest heatmap cells.",
    )
    inner = payload.get("data") or payload
    y_levels = inner.get("y") or []
    price_rows = inner.get("prices") or []
    liq = inner.get("liq") or []

    volume_by_time: dict[int, float] = defaultdict(float)
    bubbles = []
    for row in liq:
        if not isinstance(row, list) or len(row) < 3:
            continue
        time_idx, price_idx, volume = row[0], row[1], as_float(row[2])
        if volume is None:
            continue
        if not (0 <= time_idx < len(price_rows) and 0 <= price_idx < len(y_levels)):
            continue
        ts = normalize_timestamp(price_rows[time_idx][0])
        price = as_float(y_levels[price_idx])
        if ts is None or price is None:
            continue
        volume_by_time[ts] += volume
        bubbles.append({"x": ts, "y": price, "size": volume, "group": "Heatmap"})

    sorted_time = sorted(volume_by_time.items())
    panel = make_line_panel("Total Liquidation Volume By Time", [item[0] for item in sorted_time], {"Volume": [item[1] for item in sorted_time]}, wide=True)
    if panel:
        dataset["panels"].append(panel)

    panel = make_bubble_panel("Strongest Heatmap Cells", bubbles, x_mode="time", note="Bubble size represents the liquidation volume at a specific time and price level.")
    if panel:
        dataset["panels"].append(panel)

    closes = []
    close_times = []
    for row in price_rows:
        if isinstance(row, list) and len(row) >= 5:
            ts = normalize_timestamp(row[0])
            close = as_float(row[4])
            if ts is not None and close is not None:
                close_times.append(ts)
                closes.append(close)
    panel = make_line_panel("Reference Close Price", close_times, {"Close": closes})
    if panel:
        dataset["panels"].append(panel)

    dataset["stats"] = [
        {"label": "Heatmap Cells", "value": str(len(liq))},
        {"label": "Time Points", "value": str(len(price_rows))},
        {"label": "Price Levels", "value": str(len(y_levels))},
        {"label": "Price Range", "value": pretty_range(inner.get("rangeLow"), inner.get("rangeHigh"))},
    ]
    return dataset


def build_liq_map_exchange_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Exchange-level liquidation map aggregated into total liquidity by exchange and the most active price levels overall.",
    )
    totals = []
    by_price: dict[float, float] = defaultdict(float)
    for item in payload.get("data") or []:
        instrument = item.get("instrument") or {}
        exchange = instrument.get("exName", "Unknown")
        total = 0.0
        for rows in (item.get("liqMapV2") or {}).values():
            for row in rows:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                price = as_float(row[0])
                volume = as_float(row[1])
                if price is None or volume is None:
                    continue
                total += volume
                by_price[price] += volume
        totals.append((exchange, total))
    totals.sort(key=lambda item: item[1], reverse=True)

    if totals:
        panel = make_bar_panel(
            "Total Liquidation Volume By Exchange",
            [exchange for exchange, _total in totals],
            {"Volume": [total for _exchange, total in totals]},
            wide=True,
        )
        if panel:
            dataset["panels"].append(panel)

    top_prices = sorted(by_price.items(), key=lambda item: item[1], reverse=True)[:15]
    if top_prices:
        panel = make_bar_panel(
            "Top Price Levels Overall",
            [str(int(price)) if float(price).is_integer() else f"{price:.2f}" for price, _total in top_prices],
            {"Volume": [total for _price, total in top_prices]},
        )
        if panel:
            dataset["panels"].append(panel)

    rows = [[exchange, pretty_number(total)] for exchange, total in totals]
    dataset["panels"].append(make_table_panel("Exchange Totals", ["Exchange", "Total Volume"], rows))

    dataset["stats"] = [
        {"label": "Exchanges", "value": str(len(totals))},
        {"label": "Last Price", "value": pretty_number(payload.get("lastPrice"))},
        {"label": "Range", "value": pretty_range(payload.get("rangeLow"), payload.get("rangeHigh"))},
        {"label": "Top Exchange", "value": totals[0][0] if totals else "n/a"},
    ]
    return dataset


def build_hyperliq_liqmap_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Largest Hyperliquid positions aggregated by liquidation level, plus a bubble view of the biggest positions.",
    )
    positions = payload.get("list") or []
    current_price = as_float(payload.get("price")) or 0.0
    bin_size = max(250.0, round(current_price * 0.003 / 50.0) * 50.0) if current_price else 250.0
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {"Long": 0.0, "Short": 0.0})
    bubbles = []
    long_total = 0.0
    short_total = 0.0

    for row in positions:
        liq_price = as_float(row.get("liquidationPrice"))
        leverage = as_float(row.get("leverage"))
        position_usd = abs(as_float(row.get("positionUsd")) or 0.0)
        size = as_float(row.get("size")) or 0.0
        if liq_price is None or leverage is None or position_usd <= 0:
            continue
        side = "Long" if size > 0 else "Short"
        bucket = round(liq_price / bin_size) * bin_size
        grouped[f"{int(bucket):,}" if float(bucket).is_integer() else f"{bucket:.2f}"][side] += position_usd
        bubbles.append({"x": liq_price, "y": leverage, "size": position_usd, "group": side})
        if side == "Long":
            long_total += position_usd
        else:
            short_total += position_usd

    ranked_levels = sorted(
        grouped.items(),
        key=lambda item: item[1]["Long"] + item[1]["Short"],
        reverse=True,
    )[:15]

    if ranked_levels:
        panel = make_bar_panel(
            "Top Liquidation Levels",
            [label for label, _values in ranked_levels],
            {
                "Long": [values["Long"] for _label, values in ranked_levels],
                "Short": [values["Short"] for _label, values in ranked_levels],
            },
            note=f"Levels are bucketed in roughly {int(bin_size)}-point price bands.",
            wide=True,
        )
        if panel:
            dataset["panels"].append(panel)

    panel = make_bubble_panel(
        "Largest Positions",
        bubbles,
        x_mode="number",
        note="X is liquidation price, Y is leverage, and bubble size is position USD.",
    )
    if panel:
        dataset["panels"].append(panel)

    ranked_positions = sorted(
        positions,
        key=lambda row: abs(as_float(row.get("positionUsd")) or 0.0),
        reverse=True,
    )[:10]
    top_rows = [
        [
            pretty_number(row.get("liquidationPrice")),
            pretty_number(row.get("leverage")),
            pretty_number(abs(as_float(row.get("positionUsd")) or 0.0)),
            "Long" if (as_float(row.get("size")) or 0.0) > 0 else "Short",
        ]
        for row in ranked_positions
    ]
    dataset["panels"].append(make_table_panel("Position Snapshot", ["Liq Price", "Leverage", "Position USD", "Side"], top_rows))

    dataset["stats"] = [
        {"label": "Positions", "value": str(len(positions))},
        {"label": "Current Price", "value": pretty_number(current_price)},
        {"label": "Long USD", "value": pretty_number(long_total)},
        {"label": "Short USD", "value": pretty_number(short_total)},
    ]
    return dataset


def build_status_dataset(base: str, payload: dict, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "Status-style response with no plottable numeric payload in the current snapshot.",
    )
    dataset["panels"].append(make_message_panel("Raw Status", json.dumps(payload, indent=2), wide=True))
    dataset["stats"] = [
        {"label": "Success", "value": str(payload.get("success"))},
        {"label": "Code", "value": str(payload.get("code", "n/a"))},
        {"label": "Message", "value": str(payload.get("msg", "n/a"))},
        {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
    ]
    return dataset


def build_fallback_dataset(base: str, payload, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base,
        source_path,
        snapshot,
        snapshot_count,
        "This file did not match a specialized chart handler, so the dashboard shows a compact structural preview.",
    )
    preview = short_text(json.dumps(payload, indent=2))
    if isinstance(payload, list):
        dataset["stats"] = [
            {"label": "Root Type", "value": "Array"},
            {"label": "Rows", "value": str(len(payload))},
            {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
            {"label": "Preview", "value": "Fallback"},
        ]
    else:
        dataset["stats"] = [
            {"label": "Root Type", "value": "Object"},
            {"label": "Keys", "value": str(len(payload.keys())) if isinstance(payload, dict) else "n/a"},
            {"label": "Source Size", "value": human_bytes(source_path.stat().st_size)},
            {"label": "Preview", "value": "Fallback"},
        ]
    dataset["panels"].append(make_message_panel("Raw Preview", preview, wide=True))
    return dataset


def build_summary_metrics_dataset(base: str, payload: list, source_path: Path, snapshot: datetime | None, snapshot_count: int) -> dict:
    dataset = dataset_shell(
        base, source_path, snapshot, snapshot_count,
        "Computed metrics report covering heatmap cluster analysis, funding, OI, and Coinbase premium.",
    )

    sections: dict[str, list] = {}
    for row in payload:
        sec = row.get("section", "Other")
        sections.setdefault(sec, []).append(row)

    ok_count  = sum(1 for r in payload if r.get("status") == "ok")
    price_row = next((r for r in payload if r.get("metric_key") == "current_price"), None)
    price_val = price_row["value"] if price_row else "n/a"

    signal_rows = sections.get("Signal", [])
    signal_summary = "; ".join(f"{r['label']}: {r['value']}" for r in signal_rows) or "n/a"

    dataset["stats"] = [
        {"label": "Total Metrics", "value": str(len(payload))},
        {"label": "BTC Price",     "value": f"${price_val}" if price_val != "n/a" else "n/a"},
        {"label": "Data OK",       "value": f"{ok_count} / {len(payload)}"},
        {"label": "Sections",      "value": str(len(sections))},
    ]

    if signal_rows:
        dataset["notes"] = [signal_summary]

    SECTION_ORDER = ["Heatmap", "Derivatives", "Signal", "Liquidations", "On-chain", "ETF"]
    ordered = sorted(sections.keys(), key=lambda s: SECTION_ORDER.index(s) if s in SECTION_ORDER else 99)

    for sec in ordered:
        rows = sections[sec]
        table_rows = [
            [
                r.get("label", ""),
                r.get("timeframe", ""),
                r.get("value", ""),
                r.get("unit", ""),
                r.get("notes", ""),
            ]
            for r in rows
        ]
        dataset["panels"].append(
            make_table_panel(
                sec,
                ["Label", "Timeframe", "Value", "Unit", "Notes"],
                table_rows,
                wide=True,
            )
        )

    return dataset


def build_dataset(entry: dict) -> dict:
    base = entry["base"]
    path = entry["path"]
    snapshot = entry["snapshot"]
    snapshot_count = entry["snapshot_count"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        dataset = dataset_shell(base, path, snapshot, snapshot_count, "The JSON file could not be parsed.")
        dataset["stats"] = [
            {"label": "Status", "value": "Parse error"},
            {"label": "Source Size", "value": human_bytes(path.stat().st_size)},
            {"label": "File", "value": path.name},
            {"label": "Error", "value": type(exc).__name__},
        ]
        dataset["panels"].append(make_message_panel("Parse Error", str(exc), wide=True))
        return dataset

    if base == "summary_metrics" and isinstance(payload, list) and payload and isinstance(payload[0], dict) and "metric_key" in payload[0]:
        return build_summary_metrics_dataset(base, payload, path, snapshot, snapshot_count)
    if base in {"heatmap_3d", "heatmap_7d"} and isinstance(payload, dict):
        return build_raw_heatmap_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "raw_BTC" and isinstance(payload, dict):
        return build_raw_heatmap_dataset(base, payload, path, snapshot, snapshot_count)
    if base in {"oi_expiry", "delivery_volume"} and isinstance(payload, dict):
        return build_expiry_dataset(base, payload, path, snapshot, snapshot_count)
    if base in {"options_oi", "oi_chart_v3", "vol_chart", "funding_rate_history"} and isinstance(payload, dict):
        return build_map_timeseries_dataset(base, payload, path, snapshot, snapshot_count)
    if base in {"oi_stats", "oi_stats_altcoin"} and isinstance(payload, dict):
        return build_simple_lists_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "options_vs_futures" and isinstance(payload, dict):
        return build_options_vs_futures_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "options_greeks" and isinstance(payload, dict):
        return build_options_greeks_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "max_pain" and isinstance(payload, list):
        return build_max_pain_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "liq_count_heatmap" and isinstance(payload, list):
        return build_liq_count_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "hyperliq_ratio" and isinstance(payload, list):
        return build_hyperliq_ratio_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "oi_info" and isinstance(payload, list):
        return build_oi_info_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "insurance_fund" and isinstance(payload, list):
        return build_insurance_fund_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "btc_dominance" and isinstance(payload, list):
        return build_btc_dominance_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "liq_map_exchange" and isinstance(payload, dict):
        return build_liq_map_exchange_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "hyperliq_liqmap" and isinstance(payload, dict):
        return build_hyperliq_liqmap_dataset(base, payload, path, snapshot, snapshot_count)
    if base == "liq_heatmap_binance" and isinstance(payload, dict):
        if payload.get("liq"):
            return build_raw_heatmap_dataset(base, payload, path, snapshot, snapshot_count)
        return build_status_dataset(base, payload, path, snapshot, snapshot_count)

    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        return build_array_timeseries_dataset(base, payload, path, snapshot, snapshot_count)
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        for time_key in ["timestamp", "dateTime", "createTime", "time"]:
            if time_key in payload[0]:
                return build_object_timeseries_dataset(base, payload, path, snapshot, snapshot_count, time_key)
    if isinstance(payload, dict) and "dateList" in payload:
        return build_map_timeseries_dataset(base, payload, path, snapshot, snapshot_count)
    return build_fallback_dataset(base, payload, path, snapshot, snapshot_count)


def build_output_dashboard(output_dir: Path = OUTPUT_DIR) -> dict:
    output_dir.mkdir(exist_ok=True)
    latest_sources = collect_latest_sources(output_dir)
    datasets = [build_dataset(entry) for entry in latest_sources]
    snapshots = [entry["snapshot"] for entry in latest_sources if entry["snapshot"] is not None]
    newest_snapshot = max(snapshots) if snapshots else None
    total_json_files = len(list(output_dir.glob("*.json")))

    payload = {
        "summary": (
            f"Showing the latest snapshot for {len(datasets)} dataset types from {total_json_files} JSON files in the output folder. "
            f"The page is generated locally so it can be opened directly by double-clicking {HTML_NAME}."
        ),
        "overview": [
            {"label": "Dataset Types", "value": str(len(datasets))},
            {"label": "JSON Files Scanned", "value": str(total_json_files)},
            {"label": "Latest Snapshot", "value": newest_snapshot.strftime("%Y-%m-%d %H:%M:%S") if newest_snapshot else "Unknown"},
            {"label": "Generated At", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        ],
        "datasets": datasets,
    }

    html_path = output_dir / HTML_NAME
    data_js_path = output_dir / DATA_JS_NAME
    html_path.write_text(HTML_TEMPLATE, encoding="utf-8")
    data_js_path.write_text("window.DASHBOARD_DATA = " + json.dumps(payload, ensure_ascii=True) + ";\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_DIR
    result = build_output_dashboard(target)
    print(f"Built dashboard for {len(result['datasets'])} dataset types in {target}.")
