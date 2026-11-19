/* Small SVG chart helpers for the strategy report. Colors come from CSS tokens. */
const NS = "http://www.w3.org/2000/svg";
function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const fmtR = (v) => (v < 0 ? "−₹" : "₹") + Math.abs(Math.round(v)).toLocaleString("en-IN");
const fmtSigned = (v) => (v > 0 ? "+" : "") + fmtR(v).replace("−", "−");
function niceTicks(min, max, n = 5) {
  const span = max - min || 1;
  const step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}
function tooltip(host) {
  let t = host.querySelector(".tip");
  if (!t) { t = document.createElement("div"); t.className = "tip"; t.hidden = true; host.appendChild(t); }
  return {
    show(html, x, y) {
      t.innerHTML = html; t.hidden = false;
      const hw = host.clientWidth, tw = t.offsetWidth;
      t.style.left = Math.min(Math.max(x + 12, 0), hw - tw - 4) + "px";
      t.style.top = Math.max(y - t.offsetHeight - 10, 0) + "px";
    },
    hide() { t.hidden = true; },
  };
}

/* Cumulative-equity line chart. series: [{name, cls, values:[{label, y}]}] */
function lineChart(host, series, { height = 300, oosLabel = null, yFmt = fmtR } = {}) {
  host.classList.add("chart");
  const W = 760, H = height, m = { l: 64, r: 16, t: 14, b: 30 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, host);
  const n = Math.max(...series.map((s) => s.values.length));
  const ys = series.flatMap((s) => s.values.map((v) => v.y)).concat([0]);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const X = (i) => m.l + (i / Math.max(n - 1, 1)) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  for (const t of niceTicks(lo, hi, 5)) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 ? "axis" : "grid" }, svg);
    el("text", { x: m.l - 8, y: Y(t) + 4, class: "tick", "text-anchor": "end" }, svg).textContent = yFmt(t);
  }
  const labels = series[0].values.map((v) => v.label);
  const step = Math.ceil(n / 6);
  labels.forEach((lb, i) => {
    if (i % step === 0) el("text", { x: X(i), y: H - 8, class: "tick", "text-anchor": "middle" }, svg).textContent = lb;
  });
  if (oosLabel != null) {
    const i = labels.indexOf(oosLabel);
    if (i >= 0) {
      el("rect", { x: X(i), y: m.t, width: W - m.r - X(i), height: H - m.t - m.b, class: "oos-band" }, svg);
      el("text", { x: X(i) + 6, y: m.t + 14, class: "tick strong" }, svg).textContent = "Held-back test period";
    }
  }
  for (const s of series) {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v.y).toFixed(1)}`).join("");
    el("path", { d, class: `line ${s.cls}` }, svg);
    const last = s.values[s.values.length - 1];
    el("circle", { cx: X(s.values.length - 1), cy: Y(last.y), r: 4, class: `dot ${s.cls}` }, svg);
  }
  const cross = el("line", { y1: m.t, y2: H - m.b, class: "cross", visibility: "hidden" }, svg);
  const tip = tooltip(host);
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (n - 1))));
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
    const rows = series.filter((s) => s.values[i]).map((s) =>
      `<div class="tip-row"><span class="sw ${s.cls}"></span>${s.name}<b>${yFmt(s.values[i].y)}</b></div>`).join("");
    tip.show(`<div class="tip-h">${labels[i]}</div>${rows}`, (X(i) / W) * r.width, ev.clientY - r.top);
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); });
}

/* Horizontal bars for gross / costs / net per timeframe; value labels in a right-hand column. */
function moneyBars(host, rows) {
  host.classList.add("chart");
  const W = 760, rowH = 92, m = { l: 16, r: 200, t: 8, b: 26 };
  const H = m.t + m.b + rows.length * rowH;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, host);
  const vals = rows.flatMap((r) => [r.gross, -r.costs, r.net, 0]);
  const lo = Math.min(...vals) * 1.05, hi = Math.max(...vals) * 1.05 || 1;
  const X = (v) => m.l + ((v - lo) / (hi - lo)) * (W - m.l - m.r);
  for (const t of niceTicks(lo, hi, 6)) {
    el("line", { x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: t === 0 ? "axis" : "grid" }, svg);
    el("text", { x: X(t), y: H - 8, class: "tick", "text-anchor": "middle" }, svg).textContent = fmtR(t);
  }
  const tip = tooltip(host);
  rows.forEach((r, k) => {
    const y0 = m.t + k * rowH;
    el("text", { x: m.l, y: y0 + 14, class: "lab" }, svg).textContent = `${r.label} · ${r.trades} trades`;
    [["Before costs", r.gross, "b-gross"], ["Costs", -r.costs, "b-cost"], ["After costs", r.net, "b-net"]].forEach(([nm, v, cls], j) => {
      const y = y0 + 22 + j * 21, x0 = X(0), x1 = X(v);
      const rect = el("rect", { x: Math.min(x0, x1), y, width: Math.max(Math.abs(x1 - x0), 1), height: 17, rx: 3, class: cls }, svg);
      el("text", { x: W - m.r + 14, y: y + 13, class: "val" }, svg).textContent = nm;
      el("text", { x: W - 4, y: y + 13, class: "val", "text-anchor": "end" }, svg).textContent = fmtR(v);
      rect.addEventListener("pointermove", (ev) => {
        const b = svg.getBoundingClientRect();
        tip.show(`<div class="tip-h">${r.label}</div><div class="tip-row">${nm}<b>${fmtR(v)}</b></div><div class="tip-row">Per trade<b>${fmtR(v / r.trades)}</b></div>`, ev.clientX - b.left, ev.clientY - b.top);
      });
      rect.addEventListener("pointerleave", () => tip.hide());
    });
  });
}

/* Heatmap table: rows x cols with diverging fill around zero. */
function heatTable(host, { rows, cols, cell, rowLabel, colLabel }) {
  const vals = rows.flatMap((r) => cols.map((c) => cell(r, c)).filter((v) => v != null));
  const mx = Math.max(...vals.map(Math.abs)) || 1;
  let h = `<table class="heat"><thead><tr><th>${rowLabel} \\ ${colLabel}</th>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
  for (const r of rows) {
    h += `<tr><th>${r}</th>`;
    for (const c of cols) {
      const v = cell(r, c);
      if (v == null) { h += `<td>–</td>`; continue; }
      const a = Math.min(Math.abs(v) / mx, 1);
      const step = Math.ceil(a * 4);
      h += `<td class="${v >= 0 ? "pos" : "neg"}${step}" title="${fmtR(v)}">${fmtR(v)}</td>`;
    }
    h += `</tr>`;
  }
  host.innerHTML = h + `</tbody></table>`;
}

/* Candle chart of one real session with EMA, Supertrend and trade markers. */
function candleChart(host, d) {
  host.classList.add("chart");
  const W = 760, H = 420, m = { l: 12, r: 64, t: 14, b: 26 }, macdH = 90, gap = 18;
  const pH = H - m.t - m.b - macdH - gap;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, host);
  const n = d.bars.length;
  const lo = Math.min(...d.bars.map((b) => b.l), ...d.st.filter(Boolean)) - 8;
  const hi = Math.max(...d.bars.map((b) => b.h), ...d.st.filter(Boolean)) + 8;
  const cw = (W - m.l - m.r) / n;
  const X = (i) => m.l + cw * (i + 0.5);
  const Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * pH;
  for (const t of niceTicks(lo, hi, 5)) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: "grid" }, svg);
    el("text", { x: W - m.r + 6, y: Y(t) + 4, class: "tick" }, svg).textContent = t.toLocaleString("en-IN");
  }
  d.bars.forEach((b, i) => {
    if (b.t.endsWith(":15") && (b.t.startsWith("09") || b.t.startsWith("11") || b.t.startsWith("13") || b.t.startsWith("15")) || (b.t.endsWith(":00") && ["10", "12", "14"].includes(b.t.slice(0, 2))))
      el("text", { x: X(i), y: H - 8, class: "tick", "text-anchor": "middle" }, svg).textContent = b.t;
  });
  // supertrend
  for (let i = 1; i < n; i++) {
    if (d.st[i] == null || d.st[i - 1] == null || d.sd[i] !== d.sd[i - 1]) continue;
    el("line", { x1: X(i - 1), x2: X(i), y1: Y(d.st[i - 1]), y2: Y(d.st[i]), class: d.sd[i] === 1 ? "st-up" : "st-dn" }, svg);
  }
  const path = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  el("path", { d: path(d.ef), class: "ema-f" }, svg);
  el("path", { d: path(d.es), class: "ema-s" }, svg);
  d.bars.forEach((b, i) => {
    const up = b.c >= b.o;
    el("line", { x1: X(i), x2: X(i), y1: Y(b.h), y2: Y(b.l), class: up ? "wick up" : "wick dn" }, svg);
    el("rect", { x: X(i) - cw * 0.34, width: cw * 0.68, y: Y(Math.max(b.o, b.c)), height: Math.max(Math.abs(Y(b.o) - Y(b.c)), 1), class: up ? "body up" : "body dn" }, svg);
  });
  // trade levels
  for (const tr of d.trades) {
    const a = tr.i_in, z = tr.i_out;
    const lvl = (v, cls, txt) => {
      el("line", { x1: X(a), x2: X(z), y1: Y(v), y2: Y(v), class: cls }, svg);
      el("text", { x: X(z) + 4, y: Y(v) + 4, class: "tick strong" }, svg).textContent = txt;
    };
    lvl(tr.entry, "lv-entry", "Entry");
    lvl(tr.sl, "lv-sl", "SL");
    lvl(tr.tgt, "lv-tgt", "2R");
    const up = tr.side === 1;
    el("path", { d: up ? `M${X(a)},${Y(tr.entry) + 22} l-6,10 h12 z` : `M${X(a)},${Y(tr.entry) - 22} l-6,-10 h12 z`, class: up ? "mk-up" : "mk-dn" }, svg);
    el("circle", { cx: X(z), cy: Y(tr.exit), r: 5, class: "mk-exit" }, svg);
  }
  // MACD panel
  const my0 = m.t + pH + gap;
  const mv = d.macd.concat(d.sig, d.hist);
  const mlo = Math.min(...mv), mhi = Math.max(...mv);
  const MY = (v) => my0 + (1 - (v - mlo) / (mhi - mlo || 1)) * macdH;
  el("line", { x1: m.l, x2: W - m.r, y1: MY(0), y2: MY(0), class: "axis" }, svg);
  d.hist.forEach((v, i) => el("rect", { x: X(i) - cw * 0.3, width: cw * 0.6, y: Math.min(MY(0), MY(v)), height: Math.abs(MY(v) - MY(0)), class: v >= 0 ? "h-up" : "h-dn" }, svg));
  el("path", { d: d.macd.map((v, i) => `${i ? "L" : "M"}${X(i)},${MY(v)}`).join(""), class: "macd-l" }, svg);
  el("path", { d: d.sig.map((v, i) => `${i ? "L" : "M"}${X(i)},${MY(v)}`).join(""), class: "macd-s" }, svg);
  el("text", { x: W - m.r + 6, y: my0 + 12, class: "tick" }, svg).textContent = "MACD";
  // hover
  const tip = tooltip(host);
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
  const cross = el("line", { y1: m.t, y2: H - m.b, class: "cross", visibility: "hidden" }, svg);
  hit.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.floor((((ev.clientX - r.left) / r.width) * W - m.l) / cw)));
    const b = d.bars[i];
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
    tip.show(`<div class="tip-h">${b.t}</div>
      <div class="tip-row">Open / Close<b>${b.o.toFixed(0)} / ${b.c.toFixed(0)}</b></div>
      <div class="tip-row">EMA ${d.fast} / ${d.slow}<b>${d.ef[i].toFixed(0)} / ${d.es[i].toFixed(0)}</b></div>
      <div class="tip-row">Supertrend<b>${d.sd[i] === 1 ? "Up" : "Down"} ${d.st[i].toFixed(0)}</b></div>
      <div class="tip-row">MACD − signal<b>${(d.macd[i] - d.sig[i]).toFixed(1)}</b></div>`, (X(i) / W) * r.width, ev.clientY - r.top);
  });
  hit.addEventListener("pointerleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); });
}

/* Expiry payoff of a credit spread, with live inputs. */
function payoffChart(host, { side, spot, short, hedge, credit, lot }) {
  host.innerHTML = ""; host.classList.add("chart");
  const W = 760, H = 260, m = { l: 70, r: 16, t: 16, b: 30 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, host);
  const width = Math.abs(short - hedge);
  const pnl = (S) => {
    const sv = side === "put" ? Math.max(short - S, 0) - Math.max(hedge - S, 0) : Math.max(S - short, 0) - Math.max(S - hedge, 0);
    return (credit - sv) * lot;
  };
  const x0 = Math.min(short, hedge) - width * 1.2, x1 = Math.max(short, hedge) + width * 1.2;
  const lo = (credit - width) * lot * 1.25, hi = credit * lot * 1.6;
  const X = (s) => m.l + ((s - x0) / (x1 - x0)) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  for (const t of niceTicks(lo, hi, 5)) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 ? "axis" : "grid" }, svg);
    el("text", { x: m.l - 8, y: Y(t) + 4, class: "tick", "text-anchor": "end" }, svg).textContent = fmtR(t);
  }
  for (const t of niceTicks(x0, x1, 6))
    el("text", { x: X(t), y: H - 8, class: "tick", "text-anchor": "middle" }, svg).textContent = t.toLocaleString("en-IN");
  const pts = []; for (let s = x0; s <= x1; s += (x1 - x0) / 200) pts.push([s, pnl(s)]);
  const d = pts.map(([s, v], i) => `${i ? "L" : "M"}${X(s).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  el("path", { d: d + `L${X(x1)},${Y(0)}L${X(x0)},${Y(0)}Z`, class: "pay-area" }, svg);
  el("path", { d, class: "pay-line" }, svg);
  const be = side === "put" ? short - credit : short + credit;
  [[short, "Sold " + short], [hedge, "Hedge " + hedge], [be, "Breakeven " + Math.round(be)]].forEach(([v, t], k) => {
    el("line", { x1: X(v), x2: X(v), y1: m.t, y2: H - m.b, class: k === 2 ? "lv-entry" : "grid" }, svg);
    el("text", { x: X(v) + 4, y: m.t + 12 + k * 14, class: "tick strong" }, svg).textContent = t;
  });
  el("circle", { cx: X(spot), cy: Y(pnl(spot)), r: 5, class: "mk-exit" }, svg);
  const tip = tooltip(host);
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
  hit.addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect();
    const s = x0 + ((((ev.clientX - r.left) / r.width) * W - m.l) / (W - m.l - m.r)) * (x1 - x0);
    tip.show(`<div class="tip-h">Nifty at expiry ${Math.round(s).toLocaleString("en-IN")}</div><div class="tip-row">P&amp;L per lot<b>${fmtR(pnl(s))}</b></div>`, ev.clientX - r.left, ev.clientY - r.top);
  });
  hit.addEventListener("pointerleave", () => tip.hide());
}

/* Monthly grouped columns: one column per series per month, around a zero line. */
function monthBars(host, rows, series) {
  host.innerHTML = ""; host.classList.add("chart");
  const W = 760, H = 300, m = { l: 70, r: 12, t: 14, b: 34 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, host);
  const vals = rows.flatMap((r) => series.map((s) => r[s.key])).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  for (const t of niceTicks(lo, hi, 5)) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 ? "axis" : "grid" }, svg);
    el("text", { x: m.l - 8, y: Y(t) + 4, class: "tick", "text-anchor": "end" }, svg).textContent = fmtR(t);
  }
  const gw = (W - m.l - m.r) / rows.length, bw = Math.min(16, (gw - 8) / series.length - 2);
  const tip = tooltip(host);
  rows.forEach((r, i) => {
    const cx = m.l + gw * (i + 0.5);
    const d = new Date(r.month + "-01");
    el("text", { x: cx, y: H - 18, class: "tick", "text-anchor": "middle" }, svg).textContent = d.toLocaleDateString("en-GB", { month: "short" });
    if (i === 0 || d.getMonth() === 0) el("text", { x: cx, y: H - 4, class: "tick", "text-anchor": "middle" }, svg).textContent = d.getFullYear();
    series.forEach((s, j) => {
      const v = r[s.key];
      if (v == null) return;
      const x = cx + (j - (series.length - 1) / 2) * (bw + 2) - bw / 2;
      const y0 = Y(0), y1 = Y(v);
      el("rect", { x, y: Math.min(y0, y1), width: bw, height: Math.max(Math.abs(y1 - y0), 1), rx: 2, class: `col ${s.cls}` }, svg);
    });
    const hit = el("rect", { x: cx - gw / 2, y: m.t, width: gw, height: H - m.t - m.b, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (ev) => {
      const b = svg.getBoundingClientRect();
      tip.show(`<div class="tip-h">${d.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</div>` +
        series.map((s) => `<div class="tip-row"><span class="sw ${s.cls}"></span>${s.name}<b>${r[s.key] == null ? "–" : fmtR(r[s.key])}</b></div>`).join("") +
        (r.trades != null ? `<div class="tip-row">Trades<b>${r.trades}</b></div>` : ""), ev.clientX - b.left, ev.clientY - b.top);
    });
    hit.addEventListener("pointerleave", () => tip.hide());
  });
}
