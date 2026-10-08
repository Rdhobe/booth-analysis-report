"use client";

import { inr, partyIcon } from "@/lib/upbi";

export function Gauge({ pct, label }) {
  const p = Math.min(100, Math.max(0, pct || 0));
  const a = (Math.PI * (1 - p / 100)).toFixed(4);
  const x = (50 + 40 * Math.cos(a)).toFixed(1);
  const y = (50 - 40 * Math.sin(a)).toFixed(1);
  return (
    <svg width="120" height="70" viewBox="0 0 100 60">
      <path d="M10,50 A40,40 0 0 1 90,50" fill="none" stroke="#ffffff55" strokeWidth="10" strokeLinecap="round" />
      <path d={`M10,50 A40,40 0 0 1 ${x},${y}`} fill="none" stroke="#fff" strokeWidth="10" strokeLinecap="round" />
      <text x="50" y="48" textAnchor="middle" fill="#fff" fontSize="13" fontWeight="800">{label}</text>
    </svg>
  );
}

export function PartyIcon({ code }) {
  const src = partyIcon(code);
  if (!src) return null;
  return (
    <img
      className="plico"
      src={src}
      alt=""
      onError={(e) => {
        e.currentTarget.style.display = "none";
      }}
    />
  );
}

export function PartyBars({ items }) {
  const mx = Math.max(...items.map((i) => Math.abs(i[1]) || 0), 0) || 1;
  return (
    <div>
      {items.map(([label, v], i) => {
        const w = Math.max((Math.abs(v || 0) / mx) * 100, 1.5).toFixed(1);
        return (
          <div className="bar-row" key={i}>
            <span className="lbl">
              <PartyIcon code={label} />
              {label}
            </span>
            <span className="track">
              <span className={`bar${(v || 0) < 0 ? " neg" : ""}`} style={{ width: `${w}%` }} />
            </span>
            <span className="val">{inr(v)}</span>
          </div>
        );
      })}
    </div>
  );
}

const YRMAP = { VS2017: "2017", LS2019: "2019", VS2022: "2022", LS2024: "2024" };

export function Donut({ segs, size = 110 }) {
  // segs: [[label, value, color]]
  const tot = segs.reduce((a, s) => a + s[1], 0) || 1;
  let acc = 0;
  const arcs = segs.map(([label, v, color], i) => {
    const a0 = (acc / tot) * 2 * Math.PI;
    const a1 = ((acc += v) / tot) * 2 * Math.PI;
    const R = 40;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const x0 = 50 + R * Math.cos(a0);
    const y0 = 50 + R * Math.sin(a0);
    const x1 = 50 + R * Math.cos(a1);
    const y1 = 50 + R * Math.sin(a1);
    return (
      <path
        key={i}
        d={`M50,50 L${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 ${large} 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z`}
        fill={color}
        opacity="0.92"
      >
        <title>{`${label}: ${v}`}</title>
      </path>
    );
  });
  return (
    <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
      <svg width={size} height={size} viewBox="0 0 100 100">
        {arcs}
      </svg>
      <div>
        {segs.map(([label, v, color], i) => (
          <div className="small" key={i}>
            <span style={{ color }}>■</span> {label} <b>{v}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

export function TrendChart({ points }) {
  // points: [{label, share, seats}] -> share line + seat labels
  const W = 560;
  const H = 190;
  const PAD = 34;
  const shares = points.map((p) => p.share).filter((v) => v != null);
  const lo = Math.max(0, Math.min(...shares) - 5);
  const hi = Math.max(...shares) + 3;
  const X = (i) => PAD + (i * (W - PAD * 2)) / Math.max(1, points.length - 1);
  const Y = (v) => H - PAD - ((v - lo) / Math.max(1, hi - lo)) * (H - PAD * 2);
  const line = points
    .map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${p.share != null ? Y(p.share).toFixed(1) : H - PAD}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1={PAD} x2={W - PAD} y1={PAD + f * (H - PAD * 2)} y2={PAD + f * (H - PAD * 2)} stroke="#e9dcc2" strokeWidth="1" />
      ))}
      <path d={line} fill="none" stroke="#e8721c" strokeWidth="3" strokeLinejoin="round" />
      {points.map((p, i) => (
        <g key={i}>
          {p.share != null && (
            <>
              <circle cx={X(i)} cy={Y(p.share)} r="5" fill="#e8721c" stroke="#fff" strokeWidth="2" />
              <text x={X(i)} y={Y(p.share) - 12} textAnchor="middle" fontSize="12" fontWeight="800" fill="#332619">
                {p.share.toFixed(1)}%
              </text>
              <text x={X(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="#8a7760">
                {p.label} · {p.seats != null ? `${p.seats} ${p.seatWord}` : "—"}
              </text>
            </>
          )}
        </g>
      ))}
    </svg>
  );
}

export function SexPie({ rows }) {
  // Per election: pie of polled M/F + percentages + counts.
  return (
    <div className="sex">
      {rows.map((r) => {
        const m = r.male || 0;
        const f = r.female || 0;
        const tot = m + f;
        if (!tot)
          return (
            <div className="sexrow" key={r.election}>
              <span className="yr">{YRMAP[r.election] || r.election}</span>
              <span className="muted small">M/F split unavailable (official totals carry no sex split)</span>
            </div>
          );
        const mp = (100 * m) / tot;
        const fp = 100 - mp;
        return (
          <div className="sexrow" key={r.election}>
            <span className="yr">{YRMAP[r.election] || r.election}</span>
            <svg width="56" height="56" viewBox="0 0 42 42">
              <circle cx="21" cy="21" r="15.9" fill="none" stroke="#f0e8d5" strokeWidth="7" />
              <circle cx="21" cy="21" r="15.9" fill="none" stroke="#2456a6" strokeWidth="7"
                pathLength="100" strokeDasharray={`${mp.toFixed(1)} 100`} strokeDashoffset="25" />
              <circle cx="21" cy="21" r="15.9" fill="none" stroke="#e0508a" strokeWidth="7"
                pathLength="100" strokeDasharray={`${fp.toFixed(1)} 100`} strokeDashoffset={(25 - mp).toFixed(1)} />
            </svg>
            <div className="sbars">
              <div className="sbar">
                <span className="track">
                  <i style={{ width: `${mp.toFixed(1)}%`, background: "#2456a6" }} />
                </span>
                <span className="val">♂ {mp.toFixed(1)}%</span>
              </div>
              <div className="sbar">
                <span className="track">
                  <i style={{ width: `${fp.toFixed(1)}%`, background: "#e0508a" }} />
                </span>
                <span className="val">♀ {fp.toFixed(1)}%</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function SexBars({ rows }) {
  return <SexPie rows={rows} />;
}

