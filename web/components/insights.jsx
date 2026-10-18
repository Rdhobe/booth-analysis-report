"use client";

// Charts for the Insights pages (Phase 1 models). Hand-rolled SVG like the rest of the app, no chart library.
// Series colors are CSS variables (--f-*), validated for colour-blind separation in globals.css.
import { useRef, useState } from "react";

export const FRONT = {
  NDA: { name: "BJP-led (NDA)", short: "BJP-led", i: 0, color: "var(--f-nda)", on: "var(--f-nda-on)" },
  OPP: { name: "SP/INC bloc", short: "SP/INC", i: 1, color: "var(--f-opp)", on: "var(--f-opp-on)" },
  BSP: { name: "BSP", short: "BSP", i: 2, color: "var(--f-bsp)", on: "var(--f-bsp-on)" },
  OTH: { name: "Others and NOTA", short: "Others", i: 3, color: "var(--f-oth)", on: "var(--f-oth-on)" },
};
export const ORDER = ["NDA", "OPP", "BSP", "OTH"];
export const ELABEL = { VS2012: "Assembly 2012", VS2017: "Assembly 2017", LS2019: "Lok Sabha 2019", VS2022: "Assembly 2022", LS2024: "Lok Sabha 2024" };
export const ESHORT = { VS2012: "2012", VS2017: "2017", LS2019: "LS 2019", VS2022: "2022", LS2024: "LS 2024" };
const YEAR = { VS2012: 2012, VS2017: 2017, VS2022: 2022, LS2024: 2024 };

export const pct = (x, d = 1) => (x == null ? "n/a" : `${(x * 100).toFixed(d)}%`);
export const pts = (x, d = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(d)} pts`;

/* ---------- tooltip (shown on hover and on keyboard focus) ---------- */
function useTip() {
  const ref = useRef(null);
  const [tip, setTip] = useState(null);
  const show = (ev, content) => {
    const box = ref.current ? ref.current.getBoundingClientRect() : { left: 0, top: 0, width: 0 };
    let x, y;
    if (ev.type === "focus") {
      const r = ev.currentTarget.getBoundingClientRect();
      x = r.left + r.width / 2;
      y = r.top;
    } else {
      x = ev.clientX;
      y = ev.clientY;
    }
    setTip({ x: x - box.left, y: y - box.top, flip: x - box.left > box.width * 0.6, content });
  };
  const hide = () => setTip(null);
  const node = tip ? (
    <div
      className="ins-tip"
      role="status"
      style={{ left: tip.x, top: tip.y, transform: tip.flip ? "translate(calc(-100% - 12px), 12px)" : "translate(12px, 12px)" }}
    >
      {tip.content}
    </div>
  ) : null;
  const bind = (content, extra) => ({
    onPointerMove: (e) => { if (extra) extra(); show(e, content); },
    onPointerEnter: (e) => { if (extra) extra(); show(e, content); },
    onFocus: (e) => { if (extra) extra(); show(e, content); },
    onPointerLeave: () => hide(),
    onBlur: () => hide(),
  });
  return { ref, show, hide, node, bind };
}

function TipRow({ front, name, val }) {
  return (
    <div className="r">
      <span>
        {front ? <i className="k" style={{ background: FRONT[front].color }} /> : null}
        {name}
      </span>
      <b>{val}</b>
    </div>
  );
}

export function Legend({ items, bars }) {
  return (
    <div className={`ins-legend${bars ? " bars" : ""}`} aria-label="Legend">
      {items.map((c) => (
        <span key={c}>
          <i style={{ background: FRONT[c].color }} />
          {FRONT[c].name}
        </span>
      ))}
    </div>
  );
}

/* ---------- 100% stacked bars: one row per election (or per type) ---------- */
export function ShareBars({ rows, labelW = 92, rowH = 34, thick = 20, W = 640, aria }) {
  const tip = useTip();
  const H = rows.length * rowH + 6;
  const plotW = W - labelW - 8;
  return (
    <div className="ins-chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria || "Share of votes by front"}>
        {rows.map((r, i) => {
          const y = i * rowH + (rowH - thick) / 2 + 2;
          let x = labelW;
          const segs = ORDER.map((c, k) => {
            const start = x;
            x += r.sh[k] * plotW;
            const w = Math.max(0, r.sh[k] * plotW - 2); // 2px gap between touching segments
            if (w <= 0) return null;
            const content = (
              <>
                <div className="t">{r.label}</div>
                <TipRow front={c} name={FRONT[c].name} val={pct(r.sh[k])} />
                {r.extra ? <div className="m">{r.extra}</div> : null}
              </>
            );
            return (
              <g key={c}>
                <rect
                  x={start} y={y} width={w} height={thick} rx={3} tabIndex={0}
                  className="ins-mark" style={{ fill: FRONT[c].color }}
                  aria-label={`${r.label}, ${FRONT[c].name}, ${pct(r.sh[k])}`}
                  {...tip.bind(content)}
                />
                {w >= 38 && k < 3 ? (
                  <text x={start + w / 2} y={y + thick / 2 + 4} textAnchor="middle" className="ins-seg" style={{ fill: FRONT[c].on }}>
                    {Math.round(r.sh[k] * 100)}%
                  </text>
                ) : null}
              </g>
            );
          });
          return (
            <g key={r.label}>
              <text x={0} y={y + thick / 2 + 4} className="ins-nm">{r.label}</text>
              {segs}
            </g>
          );
        })}
      </svg>
      {tip.node}
    </div>
  );
}

/* ---------- ranked single-series bars ---------- */
function roundedEnd(x, y, w, h, r) { // square at the baseline, rounded at the data end
  r = Math.min(r, w, h / 2);
  return `M${x},${y} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${h - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-(w - r)} z`;
}

export function RankBars({ rows, aria, labelW = 128, rowH = 30, thick = 16, W = 560, valueW = 70 }) {
  const tip = useTip();
  const H = rows.length * rowH + 4;
  const plotW = W - labelW - valueW;
  const max = Math.max(...rows.map((r) => r.value));
  return (
    <div className="ins-chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria || "Ranked bars"}>
        <line className="ins-axis" x1={labelW} x2={labelW} y1={0} y2={H} />
        {rows.map((r, i) => {
          const y = i * rowH + (rowH - thick) / 2;
          const w = Math.max(3, (r.value / max) * plotW);
          const content = (
            <>
              <div className="t">{r.label}</div>
              <div className="r"><span>{r.what || "Value"}</span><b>{r.text}</b></div>
              {r.note ? <div className="m">{r.note}</div> : null}
            </>
          );
          return (
            <g key={r.label}>
              <text x={labelW - 8} y={y + thick / 2 + 4} textAnchor="end" className="ins-nm">{r.label}</text>
              <path d={roundedEnd(labelW, y, w, thick, 4)} className="ins-mark" tabIndex={0} style={{ fill: "var(--f-nda)" }}
                aria-label={`${r.label}, ${r.text}`} {...tip.bind(content)} />
              <text x={labelW + w + 8} y={y + thick / 2 + 4} className="ins-val">{r.text}</text>
            </g>
          );
        })}
      </svg>
      {tip.node}
    </div>
  );
}

/* ---------- vote share by front over four elections ---------- */
export function LineChart({ ac, elections }) {
  const tip = useTip();
  const [hover, setHover] = useState(null);
  const W = 640, H = 300, m = { l: 46, r: 84, t: 14, b: 46 };
  const camps = ["NDA", "OPP", "BSP"];
  const vals = camps.map((c) => elections.map((e) => ac.history[e].sh[FRONT[c].i]));
  const ymax = Math.min(1, Math.ceil((Math.max(...vals.flat()) + 0.02) * 10) / 10);
  const step = ymax <= 0.4 ? 0.1 : 0.2;
  const X = (yr) => m.l + ((yr - 2011) / (2025 - 2011)) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - v / ymax) * (H - m.t - m.b);
  const ticks = [];
  for (let t = 0; t <= ymax + 1e-9; t += step) ticks.push(Math.round(t * 100) / 100);
  const lastYs = camps.map((c, ci) => Y(vals[ci][3])).sort((a, b) => a - b);
  const labelsFit = lastYs.every((y, i) => i === 0 || y - lastYs[i - 1] >= 15); // direct labels only when they do not collide
  return (
    <div className="ins-chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Vote share by front in ${ac.name}, 2012 to 2024`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className={t === 0 ? "ins-axis" : "ins-grid"} x1={m.l} x2={W - m.r} y1={Y(t)} y2={Y(t)} />
            <text className="ins-tick" x={m.l - 8} y={Y(t) + 4} textAnchor="end">{Math.round(t * 100)}%</text>
          </g>
        ))}
        {elections.map((e) => (
          <text key={e} className="ins-tick" x={X(YEAR[e])} y={H - m.b + 18} textAnchor="middle">{ESHORT[e]}</text>
        ))}
        <text className="ins-tick" x={X(2024)} y={H - m.b + 32} textAnchor="middle">(general election)</text>
        {hover != null ? <line className="ins-cross" x1={X(YEAR[elections[hover]])} x2={X(YEAR[elections[hover]])} y1={m.t} y2={H - m.b} /> : null}
        {camps.map((c, ci) => {
          const col = FRONT[c].color;
          const pts3 = [0, 1, 2].map((i) => `${X(YEAR[elections[i]])},${Y(vals[ci][i])}`).join(" ");
          return (
            <g key={c}>
              <polyline points={pts3} className="ins-line" style={{ stroke: col }} />
              <line className="ins-line soft" style={{ stroke: col }} x1={X(2022)} y1={Y(vals[ci][2])} x2={X(2024)} y2={Y(vals[ci][3])} />
              {[0, 1, 2].map((i) => (
                <circle key={i} cx={X(YEAR[elections[i]])} cy={Y(vals[ci][i])} r={4.5} className="ins-ring" style={{ fill: col }} />
              ))}
              <circle cx={X(2024)} cy={Y(vals[ci][3])} r={4.5} className="ins-hollow" style={{ stroke: col }} />
              {labelsFit ? <text x={X(2024) + 12} y={Y(vals[ci][3]) + 4} className="ins-nm">{FRONT[c].short}</text> : null}
            </g>
          );
        })}
        {elections.map((e, i) => {
          const content = (
            <>
              <div className="t">{ELABEL[e]}</div>
              {camps.map((c, ci) => <TipRow key={c} front={c} name={FRONT[c].short} val={pct(vals[ci][i])} />)}
              <div className="m">Winner: {ac.history[e].winner.name} ({ac.history[e].winner.party})</div>
            </>
          );
          const label = `${ELABEL[e]}: ` + camps.map((c, ci) => `${FRONT[c].short} ${pct(vals[ci][i])}`).join(", ");
          const b = tip.bind(content, () => setHover(i));
          return (
            <rect key={e} className="ins-hit" x={X(YEAR[e]) - 34} y={m.t} width={68} height={H - m.t - m.b} tabIndex={0} aria-label={label}
              {...b} onPointerLeave={() => { setHover(null); tip.hide(); }} onBlur={() => { setHover(null); tip.hide(); }} />
          );
        })}
      </svg>
      {tip.node}
    </div>
  );
}

/* ---------- "if nothing changes": usual and wide range per front ---------- */
export function RangeChart({ ac }) {
  const tip = useTip();
  const rows = ["NDA", "OPP", "BSP"];
  const W = 560, rowH = 46, m = { l: 82, r: 92, t: 6, b: 26 };
  const H = m.t + rows.length * rowH + m.b;
  const X = (v) => m.l + v * (W - m.l - m.r);
  return (
    <div className="ins-chart" ref={tip.ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Expected range of vote share if nothing changes">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line className={t === 0 ? "ins-axis" : "ins-grid"} x1={X(t)} x2={X(t)} y1={m.t} y2={H - m.b} />
            <text className="ins-tick" x={X(t)} y={H - m.b + 16} textAnchor="middle">{Math.round(t * 100)}%</text>
          </g>
        ))}
        {rows.map((c, i) => {
          const e = ac.expected.camps[c];
          const cy = m.t + i * rowH + rowH / 2;
          const col = FRONT[c].color;
          const content = (
            <>
              <div className="t">{FRONT[c].name}</div>
              <TipRow name="Same as 2022" val={pct(e.expected)} />
              <TipRow name="Usual range" val={`${pct(e.low, 0)} to ${pct(e.high, 0)}`} />
              <TipRow name="Wide range" val={`${pct(e.stress_low, 0)} to ${pct(e.stress_high, 0)}`} />
            </>
          );
          return (
            <g key={c} tabIndex={0} className="ins-mark"
              aria-label={`${FRONT[c].name}: expected ${pct(e.expected)}, usual range ${pct(e.low)} to ${pct(e.high)}, wide range ${pct(e.stress_low)} to ${pct(e.stress_high)}`}
              {...tip.bind(content)}>
              <rect className="ins-hit" x={m.l} y={cy - rowH / 2} width={W - m.l - m.r} height={rowH} />
              <text x={m.l - 10} y={cy + 4} textAnchor="end" className="ins-nm">{FRONT[c].short}</text>
              <line className="ins-line soft" style={{ stroke: col }} x1={X(e.stress_low)} x2={X(e.stress_high)} y1={cy} y2={cy} />
              <rect x={X(e.low)} y={cy - 6} width={Math.max(4, X(e.high) - X(e.low))} height={12} rx={4} style={{ fill: col }} />
              <rect x={X(e.expected) - 1.5} y={cy - 11} width={3} height={22} rx={1.5} style={{ fill: "var(--ink)" }} />
              <text x={W - m.r + 10} y={cy + 4} className="ins-val">{`${Math.round(e.low * 100)}–${Math.round(e.high * 100)}%`}</text>
            </g>
          );
        })}
      </svg>
      {tip.node}
    </div>
  );
}
