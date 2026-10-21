"use client";

// Insights, part 2: seat watch list, what-if simulator, expected turnout, alliance transfer, and the extra seat-page panels.
// Data: /api/insights/* (server/insights_extra.py; files written by Scripts/ml/build_extra.py). Neutral by design: every front uses the same layout,
// colours are the validated chart palette (not party colours), and nothing here predicts an election.
import { useEffect, useMemo, useRef, useState } from "react";
import { get, post, inr } from "@/lib/upbi";
import { pct } from "@/components/insights";

const F5 = {
  NDA: { name: "BJP-led (NDA)", short: "BJP-led", color: "var(--f-nda)", on: "var(--f-nda-on)" },
  SPF: { name: "SP-led", short: "SP-led", color: "var(--f-opp)", on: "var(--f-opp-on)" },
  INC: { name: "INC", short: "INC", color: "var(--f-inc)", on: "var(--f-inc-on)" },
  BSP: { name: "BSP", short: "BSP", color: "var(--f-bsp)", on: "var(--f-bsp-on)" },
  OTH: { name: "Others", short: "Others", color: "var(--f-oth)", on: "var(--f-oth-on)" },
};
const ORDER5 = ["NDA", "SPF", "INC", "BSP", "OTH"];
const BOOTH_FRONT = { N: "NDA", S: "SPF", B: "BSP", O: "OTH" };
const BN = { NDA: "BJP-led (NDA)", SPF: "SP/INC bloc", BSP: "BSP", OTH: "Others" };
const BNS = { NDA: "BJP-led", SPF: "SP/INC", BSP: "BSP", OTH: "Others" };
const BANDS = ["Highest", "High", "Moderate", "Lower"];
const sgn = (x, d = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;

function useApi(path, keep = false) {
  const [state, setState] = useState({ data: null, err: "" });
  useEffect(() => {
    if (!path) return undefined;
    let live = true;
    setState((s) => ({ data: keep ? s.data : null, err: "" }));
    get(path).then((d) => live && setState({ data: d, err: "" })).catch((e) => live && setState({ data: null, err: e.message }));
    return () => { live = false; };
  }, [path, keep]);
  return state;
}

function Table({ cols, rows, empty }) {
  if (!rows.length) return <p className="muted small">{empty || "Nothing to show."}</p>;
  return (
    <div className="ins-tw">
      <table className="ins-table">
        <thead><tr>{cols.map((c) => <th key={c.label} className={c.n ? "n" : ""}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.key ?? i} className={r.hl ? "hl" : ""}>
              {cols.map((c) => <td key={c.label} className={c.n ? "n nowrap" : c.nowrap ? "nowrap" : ""}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const SeatLink = ({ onOpen, ac, children }) => <button type="button" className="ins-link" onClick={() => onOpen(ac)}>{children}</button>;
const BandPill = ({ band }) => <span className={`ins-pill band-${band}`}>{band}</span>;
const Hidden = ({ msg }) => <div className="warnbox"><b>Hidden.</b> {msg || "Compliance Mode is on: forward-looking numbers are hidden."}</div>;
const ErrBox = ({ err }) => <div className="panel err">Could not load this section: {err}</div>;

/* ============================================================ Battlegrounds (seat watch list) */
export function WatchTab({ openAc }) {
  const [band, setBand] = useState("");
  const [district, setDistrict] = useState("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(40);
  const qs = new URLSearchParams({ limit: String(limit) });
  if (band) qs.set("band", band);
  if (district) qs.set("district", district);
  if (q.trim()) qs.set("q", q.trim());
  const { data, err } = useApi(`insights/watchlist?${qs}`, true);
  if (err) return <ErrBox err={err} />;
  if (!data) return <div className="skel" />;
  if (data.hidden) return <Hidden msg={data.message} />;
  const bt = data.backtest, tr = bt.transitions, bands = bt.bands;
  const last = "VS2017->VS2022", first = "VS2012->VS2017";
  return (
    <>
      <div className="panel">
        <h2>Seats most likely to change hands</h2>
        <p className="muted">
          Every seat gets a watch score from two facts: how narrow the 2022 win was, and whether the 2024 Lok Sabha vote in that area moved against the side that won.
          It is a fixed rule (three parts closeness, one part Lok Sabha mood); nothing is fitted. It ranks seats; it does not say who will win.
        </p>
        <div className="ins-bandcards">
          {BANDS.map((b, i) => {
            const rec = bands[last].find((x) => x.band === b), old = bands[first].find((x) => x.band === b);
            return (
              <button key={b} type="button" className={`ins-bandcard ${band === b ? "on" : ""}`} onClick={() => { setBand(band === b ? "" : b); setLimit(40); }} aria-pressed={band === b}>
                <BandPill band={b} />
                <span className="ins-big">{data.band_counts[b]}</span>
                <span className="muted small">seats</span>
                <span className="small">In 2022, <b>{Math.round((rec.flip_rate || 0) * 100)}%</b> of seats in this band changed hands.</span>
                <span className="muted small">In 2017 (a wave year): {Math.round((old.flip_rate || 0) * 100)}%.</span>
              </button>
            );
          })}
        </div>
        <details>
          <summary className="muted small">How well did this work in the past?</summary>
          <p className="muted small">
            Tested on the last two assembly elections. Ranking by the rule is compared with ranking by margin alone and with a learned logistic regression trained on the other election.
            AUC is the chance that a seat that changed hands is ranked above one that did not (0.5 is guessing, 1 is perfect). Precision is the share of the top-ranked seats that really changed hands.
          </p>
          <Table
            cols={[
              { label: "Election change", cell: (r) => r.t.replace("->", " to ").replaceAll("VS", "") },
              { label: "Seats that changed hands", n: 1, cell: (r) => `${r.v.flips} of ${r.v.seats}` },
              { label: "Method", cell: (r) => r.m },
              { label: "AUC", n: 1, cell: (r) => r.s.auc.toFixed(2) },
              { label: "Top 50 precision", n: 1, cell: (r) => `${Math.round(r.s.precision_at_50 * 100)}%` },
              { label: "Top 100 precision", n: 1, cell: (r) => `${Math.round(r.s.precision_at_100 * 100)}%` },
            ]}
            rows={Object.entries(tr).flatMap(([t, v]) => Object.entries(v.scores).map(([m, s]) => ({ key: t + m, t, v, m: m === "rule" ? "Watch score (rule, used)" : m === "margin_only" ? "Margin alone" : "Learned logistic regression (not used)", s, hl: m === "rule" })))}
          />
          <p className="muted small">{bt.decision.text}</p>
        </details>
      </div>
      <div className="panel">
        <div className="toolbar">
          <label className="muted small" htmlFor="w-band">Band</label>
          <select id="w-band" value={band} onChange={(e) => { setBand(e.target.value); setLimit(40); }}>
            <option value="">All bands</option>
            {data.band_names.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <label className="muted small" htmlFor="w-dist">District</label>
          <select id="w-dist" value={district} onChange={(e) => { setDistrict(e.target.value); setLimit(40); }}>
            <option value="">All districts</option>
            {data.districts.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <input aria-label="Search seats" placeholder="Search seat or district" value={q} onChange={(e) => { setQ(e.target.value); setLimit(40); }} />
        </div>
        <Table
          cols={[
            { label: "Rank", n: 1, cell: (r) => r.rank },
            { label: "Seat", cell: (r) => <SeatLink onOpen={openAc} ac={r.ac}>{r.name}</SeatLink> },
            { label: "District", cell: (r) => r.district },
            { label: "Band", nowrap: 1, cell: (r) => <BandPill band={r.band} /> },
            { label: "Score", n: 1, cell: (r) => r.score.toFixed(0) },
            { label: "2022 margin", n: 1, cell: (r) => `${inr(r.margin_votes)} (${r.margin_pts.toFixed(1)} pts)` },
            { label: "Lok Sabha mood vs 2022 winner", n: 1, cell: (r) => (r.mood_against_leader_pts > 0 ? `${r.mood_against_leader_pts.toFixed(0)} pts against` : `${Math.abs(r.mood_against_leader_pts).toFixed(0)} pts with`) },
            { label: "Lok Sabha seat led by the other side", nowrap: 1, cell: (r) => (r.ls_disagrees ? "Yes" : "No") },
            { label: "Changed hands since 2012", n: 1, cell: (r) => `${r.past_flips} of 2` },
          ]}
          rows={data.rows}
          empty="No seats match these filters."
        />
        <p className="muted small">Showing {data.rows.length} of {data.total} seats. Click a seat name for its page and the reasons behind its score.</p>
        {data.rows.length < data.total ? <button type="button" className="ins-more" onClick={() => setLimit(limit + 60)}>Show 60 more</button> : null}
      </div>
    </>
  );
}

/* ============================================================ What-if simulator */
function SeatBar({ counts, total, label }) {
  const text = ORDER5.filter((f) => counts[f]).map((f) => `${F5[f].name} ${counts[f]}`).join(", ");
  return (
    <div className="ins-seatrow">
      <span className="ins-seatlabel">{label}</span>
      <div className="ins-seatbar" role="img" aria-label={`${label}: ${text}`}>
        {ORDER5.filter((f) => counts[f]).map((f) => (
          <span key={f} style={{ width: `${(counts[f] / total) * 100}%`, background: F5[f].color, color: F5[f].on }} title={`${F5[f].name}: ${counts[f]} seats`}>
            {counts[f] / total > 0.05 ? counts[f] : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

const ZERO = () => ({ NDA: 0, SPF: 0, BSP: 0 });

function Slider({ value, onChange, label }) {
  return (
    <label className="ins-slide">
      <input type="range" min="-10" max="10" step="0.5" value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
      <output>{sgn(value)}</output>
    </label>
  );
}

export function WhatIfTab({ openAc }) {
  const { data: setup, err } = useApi("insights/simulator/setup");
  const [preset, setPreset] = useState("repeat2022");
  const [all, setAll] = useState(ZERO());
  const [reg, setReg] = useState({});
  const [alliance, setAlliance] = useState("");
  const [rate, setRate] = useState(null);
  const [res, setRes] = useState(null);
  const [simErr, setSimErr] = useState("");
  const [regionFilter, setRegionFilter] = useState("all");
  const tick = useRef(0);

  useEffect(() => {
    if (setup && !setup.hidden && Object.keys(reg).length === 0) {
      setReg(Object.fromEntries(setup.regions.map((r) => [r.name, ZERO()])));
      setRate(setup.alliance_defaults["SP+INC"]);
    }
  }, [setup]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!setup || setup.hidden || Object.keys(reg).length === 0) return undefined;
    const id = ++tick.current;
    const t = setTimeout(() => {
      post("insights/simulate", { swing_all: all, swings: reg, alliance: alliance || null, rate: alliance ? rate : null })
        .then((d) => { if (id === tick.current) { setRes(d); setSimErr(""); } })
        .catch((e) => id === tick.current && setSimErr(e.message));
    }, 220);
    return () => clearTimeout(t);
  }, [setup, all, reg, alliance, rate]);

  if (err) return <ErrBox err={err} />;
  if (!setup) return <div className="skel" />;
  if (setup.hidden) return <Hidden msg={setup.message} />;

  const applyPreset = (id) => {
    const p = setup.presets.find((x) => x.id === id);
    setPreset(id);
    setAll(ZERO());
    setReg(Object.fromEntries(setup.regions.map((r, i) => [r.name, { NDA: +(p.swings[i][0] * 100).toFixed(1), SPF: +(p.swings[i][1] * 100).toFixed(1), BSP: +(p.swings[i][2] * 100).toFixed(1) }])));
    setAlliance(p.alliance || "");
    setRate(p.rate || setup.alliance_defaults["SP+INC"]);
  };
  const setCell = (rn, f, v) => { setPreset("custom"); setReg((s) => ({ ...s, [rn]: { ...s[rn], [f]: v } })); };
  const setAllCell = (f, v) => { setPreset("custom"); setAll((s) => ({ ...s, [f]: v })); };
  const hind = setup.hindcast.pairs["VS2017->VS2022"], pooled = setup.hindcast.bands.pooled;
  const flips = res ? res.seats.filter((s) => s.flips_vs_2022 && (regionFilter === "all" || String(s.region) === regionFilter)).sort((a, b) => a.margin_pts - b.margin_pts) : [];
  const close = res ? res.seats.filter((s) => s.margin_pts < setup.toss_up_pp && (regionFilter === "all" || String(s.region) === regionFilter)).sort((a, b) => a.margin_pts - b.margin_pts) : [];
  return (
    <>
      <div className="panel">
        <h2>What if the vote moved?</h2>
        <p className="muted">
          A calculator, not a forecast. You choose how each front{"’"}s vote share moves, in percentage points, by region. It shows which front would lead each seat on those shares.
          It does not say how voters will move. The starting point is the 2022 assembly result, which this reproduces exactly when nothing is moved.
        </p>
        <div className="ins-note">
          <b>How far to trust it.</b> We gave the calculator the <i>true</i> 2022 swing of each region, which a user never has, and checked it against what happened. It called{" "}
          <b>{hind.regional_swing.seats_called_right_pct}%</b> of seats right, about the same as repeating the previous winner ({hind.same_winner_as_before_pct}%) in a normal year, but far better in a wave year (66% against 20% in 2017).
          Seats where the leader is ahead by less than 6 points were close to coin flips ({pooled[0].leader_won_pct}% to {pooled[1].leader_won_pct}% right), so the page marks them.
        </div>
      </div>
      <div className="ins-grid2">
        <div className="panel">
          <h3>1. Starting point</h3>
          <div className="toolbar">
            <label className="muted small" htmlFor="wi-preset">Preset</label>
            <select id="wi-preset" value={preset} onChange={(e) => e.target.value !== "custom" && applyPreset(e.target.value)}>
              {setup.presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              {preset === "custom" ? <option value="custom">Your own settings</option> : null}
            </select>
          </div>
          <p className="muted small">{(setup.presets.find((p) => p.id === preset) || {}).note || "Your own settings."}</p>
          {preset === "ls2024" ? <p className="muted small">This preset reproduces the 2024 Lok Sabha leader of {setup.presets.find((p) => p.id === "ls2024").reproduces_ls2024_segment_leader_pct}% of assembly segments.</p> : null}
        </div>
        <div className="panel">
          <h3>2. Alliance</h3>
          <div className="toolbar">
            <label className="muted small" htmlFor="wi-all">Scenario</label>
            <select id="wi-all" value={alliance} onChange={(e) => { setPreset("custom"); setAlliance(e.target.value); setRate(e.target.value ? setup.alliance_defaults[e.target.value] : rate); }}>
              <option value="">As in 2022 (no new alliance)</option>
              <option value="SP+INC">SP-led front and INC stand together</option>
              <option value="SP+BSP">SP-led front and BSP stand together</option>
            </select>
          </div>
          {alliance ? (
            <label className="ins-slide wide">
              <span className="small">Share of the partner{"’"}s voters who move to the SP-led front</span>
              <input type="range" min="0" max="1" step="0.05" value={rate ?? 0} onChange={(e) => { setPreset("custom"); setRate(Number(e.target.value)); }} aria-label="Transfer rate" />
              <output>{Math.round((rate ?? 0) * 100)}%</output>
            </label>
          ) : null}
          {alliance ? <p className="muted small">Estimated from past Lok Sabha alliances (see the Alliances tab): {Math.round(setup.alliance_defaults[alliance] * 100)}%. Assembly elections can differ.</p> : <p className="muted small">Choose a scenario to merge a partner{"’"}s vote into the SP-led front before the vote is moved.</p>}
        </div>
      </div>
      <div className="ins-grid1">
        <div className="panel">
          <h3>3. Move the vote (percentage points)</h3>
          <p className="muted small">Positive adds to the front{"’"}s share. Others and INC absorb the opposite change in proportion to their size.</p>
          <div className="ins-tw">
            <table className="ins-table ins-sliders">
              <thead><tr><th>Region</th>{["NDA", "SPF", "BSP"].map((f) => <th key={f}>{F5[f].short}</th>)}</tr></thead>
              <tbody>
                <tr className="hl"><td><b>Whole state</b><div className="muted small">added to every region</div></td>
                  {["NDA", "SPF", "BSP"].map((f) => <td key={f}><Slider value={all[f]} onChange={(v) => setAllCell(f, v)} label={`Whole state, ${F5[f].name}`} /></td>)}</tr>
                {setup.regions.map((r) => (
                  <tr key={r.name}><td>{r.name}<div className="muted small">{r.seats} seats</div></td>
                    {["NDA", "SPF", "BSP"].map((f) => <td key={f}><Slider value={reg[r.name] ? reg[r.name][f] : 0} onChange={(v) => setCell(r.name, f, v)} label={`${r.name}, ${F5[f].name}`} /></td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <button type="button" className="ins-more" onClick={() => applyPreset("repeat2022")}>Reset to 2022</button>
          <p className="muted small">{setup.region_status}</p>
        </div>
      </div>
      {simErr ? <ErrBox err={simErr} /> : null}
      {res ? (
        <>
          <div className="panel">
            <h2>Which front would lead how many seats</h2>
            <SeatBar counts={setup.actual_2022} total={403} label="2022 as it happened" />
            <SeatBar counts={res.summary.leads} total={403} label="With your settings" />
            <Table
              cols={[
                { label: "Front", cell: (r) => <span><span className="ins-dot" style={{ background: F5[r.f].color }} />{F5[r.f].name}</span> },
                { label: "2022", n: 1, cell: (r) => setup.actual_2022[r.f] },
                { label: "Your settings", n: 1, cell: (r) => <b>{res.summary.leads[r.f]}</b> },
                { label: "Change", n: 1, cell: (r) => sgn(res.summary.leads[r.f] - setup.actual_2022[r.f], 0) },
                { label: "Range if close seats go either way", n: 1, cell: (r) => `${res.summary.bounds[r.f][0]} to ${res.summary.bounds[r.f][1]}` },
              ]}
              rows={ORDER5.map((f) => ({ f, key: f }))}
            />
            <p className="muted small">
              <b>{res.summary.toss_up_seats}</b> seats are within {res.summary.toss_up_rule}. The range counts every one of them against the front, then for it. {res.summary.flips_vs_2022} seats change leader compared with 2022.
              The calculator adds no random chance: with the true swing, adding random chance made seat counts worse in the tests.
            </p>
          </div>
          <div className="panel">
            <h3>By region</h3>
            <Table
              cols={[{ label: "Region", cell: (r) => r.name }, { label: "Seats", n: 1, cell: (r) => r.seats }, ...ORDER5.filter((f) => f !== "OTH").map((f) => ({ label: F5[f].short, n: 1, cell: (r) => r.leads[f] })), { label: "Others", n: 1, cell: (r) => r.leads.OTH }]}
              rows={res.regions.map((r) => ({ ...r, key: r.name }))}
            />
          </div>
          <div className="toolbar">
            <label className="muted small" htmlFor="wi-reg">Show seats in</label>
            <select id="wi-reg" value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)}>
              <option value="all">All regions</option>
              {setup.regions.map((r, i) => <option key={r.name} value={String(i)}>{r.name}</option>)}
            </select>
          </div>
          <div className="ins-grid2">
            <div className="panel">
              <h3>Seats that change leader ({flips.length})</h3>
              <Table
                cols={[
                  { label: "Seat", cell: (r) => <SeatLink onOpen={openAc} ac={r.ac}>{r.name}</SeatLink> },
                  { label: "2022 winner", cell: (r) => F5[r.winner_2022].short },
                  { label: "Now leads", cell: (r) => <b>{F5[r.lead].short}</b> },
                  { label: "Ahead by", n: 1, cell: (r) => `${r.margin_pts.toFixed(1)} pts` },
                ]}
                rows={flips.slice(0, 25).map((r) => ({ ...r, key: r.ac }))}
                empty="No seat changes leader with these settings."
              />
              {flips.length > 25 ? <p className="muted small">The 25 narrowest of {flips.length}.</p> : null}
            </div>
            <div className="panel">
              <h3>Closest seats ({close.length} within {setup.toss_up_pp} points)</h3>
              <Table
                cols={[
                  { label: "Seat", cell: (r) => <SeatLink onOpen={openAc} ac={r.ac}>{r.name}</SeatLink> },
                  { label: "Leads", cell: (r) => F5[r.lead].short },
                  { label: "Runner-up", cell: (r) => F5[r.second].short },
                  { label: "Margin", n: 1, cell: (r) => `${r.margin_pts.toFixed(1)} pts` },
                  { label: "Right in past tests", n: 1, cell: (r) => (r.history_pct != null ? `${r.history_pct}%` : "n/a") },
                ]}
                rows={close.slice(0, 25).map((r) => ({ ...r, key: r.ac }))}
                empty="No seat is this close."
              />
            </div>
          </div>
        </>
      ) : <div className="skel" />}
    </>
  );
}

/* ============================================================ Expected turnout */
function Scatter({ rows, target }) {
  const W = 560, H = 380, L = 46, R = 14, T = 12, B = 40;
  const lo = 0.35, hi = 0.8;
  const X = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const Y = (v) => H - B - ((v - lo) / (hi - lo)) * (H - T - B);
  const ticks = [0.4, 0.5, 0.6, 0.7, 0.8];
  return (
    <div className="ins-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Actual against expected turnout for ${rows.length} constituencies`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="ins-grid" x1={X(t)} x2={X(t)} y1={T} y2={H - B} />
            <line className="ins-grid" x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} />
            <text className="ins-tick" x={X(t)} y={H - B + 16} textAnchor="middle">{Math.round(t * 100)}%</text>
            <text className="ins-tick" x={L - 6} y={Y(t) + 4} textAnchor="end">{Math.round(t * 100)}%</text>
          </g>
        ))}
        <line className="ins-axis" x1={X(lo)} y1={Y(lo)} x2={X(hi)} y2={Y(hi)} strokeDasharray="4 4" />
        {rows.filter((r) => !r.flag).map((r) => <circle key={r.ac} cx={X(r.expected)} cy={Y(r.actual)} r="2.6" fill="#9aa6b3" fillOpacity="0.75"><title>{`${r.name}: actual ${pct(r.actual)}, expected ${pct(r.expected)}`}</title></circle>)}
        {rows.filter((r) => r.flag).map((r) => <circle key={r.ac} cx={X(r.expected)} cy={Y(r.actual)} r="4" fill="#2b3a4a" stroke="#fff" strokeWidth="1"><title>{`${r.name}: actual ${pct(r.actual)}, expected ${pct(r.expected)} (well below)`}</title></circle>)}
        <text className="ins-tick" x={(L + W - R) / 2} y={H - 6} textAnchor="middle">Expected turnout</text>
        <text className="ins-tick" transform={`translate(12 ${(T + H - B) / 2}) rotate(-90)`} textAnchor="middle">Actual turnout, {target}</text>
      </svg>
    </div>
  );
}

export function TurnoutTab({ openAc }) {
  const { data, err } = useApi("insights/turnout");
  const [target, setTarget] = useState("LS2024");
  const [mode, setMode] = useState("below");
  const rows = useMemo(() => (data ? data.rows.filter((r) => r.turnout[target] && r.turnout[target].actual != null).map((r) => ({ ...r, ...r.turnout[target], women: r.turnout.women_share_of_voters, key: r.ac })) : []), [data, target]);
  if (err) return <ErrBox err={err} />;
  if (!data) return <div className="skel" />;
  const tm = data.targets[target], m = tm.cv_mae_pts;
  const sorted = [...rows].sort((a, b) => (mode === "below" ? a.gap_pts - b.gap_pts : b.gap_pts - a.gap_pts)).slice(0, 20);
  const nflag = rows.filter((r) => r.flag).length;
  const womenState = data.women_share_statewide_mean;
  return (
    <>
      <div className="panel">
        <h2>Turnout against what history and peers suggest</h2>
        <p className="muted">
          For each seat the model estimates the turnout its earlier elections, its size, its growth in voters and its share of women voters would suggest, then compares it with what happened.
          A big gap is a reason to look closer. It is not a finding about why people stayed home or came out.
        </p>
        <div className="tabs" role="tablist" aria-label="Election">
          {Object.entries(data.targets).map(([k, v]) => <button key={k} type="button" role="tab" aria-selected={target === k} className={target === k ? "on" : ""} onClick={() => setTarget(k)}>{v.label}</button>)}
        </div>
        <div className="ins-grid3">
          <div className="panel ins-tile"><div className="muted small">Typical miss of the expected value</div><div className="ins-big">{m[tm.model_used.includes("ridge") ? "ridge" : tm.model_used.includes("gradient") ? "gradient_boosting" : "persistence_plus_statewide_change"].toFixed(1)} pts</div><div className="muted small">Whole districts held out when scoring. {tm.model_used}.</div></div>
          <div className="panel ins-tile"><div className="muted small">Simple rule, for comparison</div><div className="ins-big">{m.persistence_plus_statewide_change.toFixed(1)} pts</div><div className="muted small">Last same-type election plus the statewide change (known only afterwards).</div></div>
          <div className="panel ins-tile"><div className="muted small">Seats well below expected</div><div className="ins-big">{nflag}</div><div className="muted small">Gap more than {Math.abs(data.flag_z)} standard deviations ({tm.gap_sd_pts.toFixed(1)} pts each) below zero.</div></div>
        </div>
      </div>
      <div className="ins-split">
        <div className="panel">
          <h3>Actual against expected</h3>
          <p className="muted small">Each dot is a seat. Below the dashed line means turnout fell short of what was expected. Dark dots are well below.</p>
          <Scatter rows={rows} target={tm.label} />
        </div>
        <div className="panel">
          <div className="toolbar">
            <h3 style={{ margin: 0 }}>Seats furthest {mode === "below" ? "below" : "above"} expected</h3>
            <select aria-label="Direction" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="below">Below expected</option>
              <option value="above">Above expected</option>
            </select>
          </div>
          <Table
            cols={[
              { label: "Seat", cell: (r) => <SeatLink onOpen={openAc} ac={r.ac}>{r.name}</SeatLink> },
              { label: "District", cell: (r) => r.district },
              { label: "Actual", n: 1, cell: (r) => pct(r.actual) },
              { label: "Expected", n: 1, cell: (r) => pct(r.expected) },
              { label: "Gap", n: 1, cell: (r) => `${sgn(r.gap_pts)} pts` },
              { label: "Women’s share", n: 1, cell: (r) => (r.women && r.women.VS2022 != null ? `${pct(r.women.VS2022)}` : "n/a") },
            ]}
            rows={sorted}
          />
          <p className="muted small">State average women{"’"}s share of voters in 2022: {pct(womenState.VS2022)}. This is the share of voters who were women, not a turnout rate (electors by sex are not in the files).</p>
        </div>
      </div>
    </>
  );
}

/* ============================================================ Alliances */
function IntervalBar({ est, lo, hi }) {
  const W = 360, H = 36, L = 8, R = 8;
  const X = (v) => L + v * (W - L - R);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Estimate ${Math.round(est * 100)}%, interval ${Math.round(lo * 100)}% to ${Math.round(hi * 100)}%`} style={{ width: "100%", maxWidth: 380, height: "auto" }}>
      <line className="ins-axis" x1={X(0)} x2={X(1)} y1="18" y2="18" />
      {[0, 0.25, 0.5, 0.75, 1].map((t) => <line key={t} className="ins-grid" x1={X(t)} x2={X(t)} y1="12" y2="24" />)}
      <rect x={X(lo)} y="12" width={Math.max(2, X(hi) - X(lo))} height="12" rx="6" fill="var(--f-opp)" fillOpacity="0.45" />
      <rect x={X(est) - 2} y="8" width="4" height="20" rx="2" fill="#1d2733" />
    </svg>
  );
}

export function AlliancesTab() {
  const { data, err } = useApi("insights/alliances");
  if (err) return <ErrBox err={err} />;
  if (!data) return <div className="skel" />;
  return (
    <>
      <div className="panel">
        <h2>How much of a partner{"’"}s vote moved to an alliance candidate</h2>
        <p className="muted">
          When two parties ally, a seat goes to one partner{"’"}s candidate. These estimates say what share of the <i>other</i> partner{"’"}s earlier voters seem to have voted for that candidate, from how the alliance
          candidate{"’"}s vote share related to each party{"’"}s earlier share across parliamentary seats. They are statistical estimates from 37 to 62 seats each, not counts of voters.
        </p>
        <div className="ins-note">{data.caveat}</div>
      </div>
      <div className="ins-grid2">
        {data.groups.map((g) => (
          <div className="panel" key={g.label}>
            <h3>{g.election === "LS2019" ? "Lok Sabha 2019: SP, BSP and RLD" : "Lok Sabha 2024: SP and INC"}</h3>
            <p className="small">{g.label.split(": ")[1].replace(/^./, (c) => c.toUpperCase())}</p>
            <div className="ins-big">{Math.round(g.transfer_from_partner * 100)}%</div>
            <IntervalBar est={g.transfer_from_partner} lo={g.transfer_interval[0]} hi={g.transfer_interval[1]} />
            <p className="muted small">80% interval {Math.round(g.transfer_interval[0] * 100)}% to {Math.round(g.transfer_interval[1] * 100)}%, from {g.seats} seats. The candidate{"’"}s own party kept about {Math.round(g.retention_of_own * 100)}% of its earlier voters.</p>
            <p className="muted small">
              Typical miss when guessing a left-out seat: <b>{g.loo_mae_pts.fitted.toFixed(1)} pts</b>, against {g.loo_mae_pts.partner_votes_all_transfer.toFixed(1)} if every partner voter moved and {g.loo_mae_pts.partner_votes_none_transfer.toFixed(1)} if none did.
            </p>
          </div>
        ))}
      </div>
      <div className="panel">
        <h3>How this is used</h3>
        <p className="muted small">{data.method}</p>
        <p className="muted small">The What-if tab uses these as the starting transfer rates for an alliance scenario ({Math.round(data.defaults.BSP_to_SP.rate * 100)}% for BSP voters, {Math.round(data.defaults.INC_to_SP.rate * 100)}% for INC voters); you can change them.</p>
      </div>
    </>
  );
}

/* ============================================================ seat page: watch, turnout, booths */
export function SeatExtraPanels({ ac, boot }) {
  const x = ac.extra;
  if (!x) return null;
  const wb = boot.card && boot.card.extra_models ? boot.card.extra_models.watch.bands["VS2017->VS2022"] : null;
  const w = x.watch;
  const band = w && wb ? wb.find((b) => b.band === w.band) : null;
  const tl = x.turnout;
  const Row = ({ label, t }) => (t && t.actual != null ? (
    <tr>
      <td>{label}</td><td className="n">{pct(t.actual)}</td><td className="n">{pct(t.expected)}</td>
      <td className="n">{sgn(t.gap_pts)} pts</td><td className="n">{t.rank_lowest} of 403</td>
      <td>{t.flag ? <span className="ins-pill warn">Well below expected</span> : <span className="muted small">Within the usual range</span>}</td>
    </tr>
  ) : <tr><td>{label}</td><td colSpan="5" className="muted small">No trusted turnout figure for this seat.</td></tr>);
  return (
    <>
      <div className="ins-grid2">
        <div className="panel">
          <h2>Watch score</h2>
          {w == null ? (
            <Hidden msg={x.watch_hidden} />
          ) : (
            <>
              <p className="muted small">How likely this seat is to change hands, compared with the other 402. A ranking, not a forecast.</p>
              <div className="ins-chips"><BandPill band={w.band} /><span className="ins-pill">Rank {w.rank} of 403</span><span className="ins-pill">Score {w.score.toFixed(0)} of 100</span></div>
              <ul className="ins-list">{w.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              <p className="muted small">
                Changed hands {w.past_flips} of the last 2 assembly elections.
                {band ? ` In 2022, ${Math.round(band.flip_rate * 100)}% of seats in the ${w.band} band changed hands.` : ""}
              </p>
            </>
          )}
        </div>
        <div className="panel">
          <h2>Turnout against expected</h2>
          <p className="muted small">What this seat{"’"}s history, size and peers suggest, against what happened.</p>
          <div className="ins-tw">
            <table className="ins-table">
              <thead><tr><th>Election</th><th className="n">Actual</th><th className="n">Expected</th><th className="n">Gap</th><th className="n">Rank (lowest = 1)</th><th>Reading</th></tr></thead>
              <tbody><Row label="Assembly 2022" t={tl.VS2022} /><Row label="Lok Sabha 2024" t={tl.LS2024} /></tbody>
            </table>
          </div>
          {tl.women_share_of_voters ? <p className="muted small">Women{"’"}s share of voters: {["VS2017", "LS2019", "VS2022"].map((e) => `${e === "LS2019" ? "LS 2019" : e.slice(2)} ${tl.women_share_of_voters[e] != null ? pct(tl.women_share_of_voters[e]) : "n/a"}`).join(" · ")}.</p> : null}
        </div>
      </div>
      <BoothPanel ac={ac} />
    </>
  );
}

const csvOf = (b) => ["booth,leading_front,margin_pts,valid_votes", ...b.rows.map((r) => `${r[0]},${BOOTH_FRONT[r[1]]},${r[2]},${r[3]}`)].join("\n");

function BoothPanel({ ac }) {
  const avail = ac.extra && ac.extra.booths && ac.extra.booths.available;
  const { data, err } = useApi(avail ? `insights/booths/${ac.ac}` : null);
  if (!avail) {
    return (
      <div className="panel">
        <h2>Booths, Lok Sabha 2024</h2>
        <p className="muted">No booth segments for this seat yet: its 2024 booth sheet has not been checked against the official totals. Booth segments cover only seats whose sheet matches exactly.</p>
      </div>
    );
  }
  if (err) return <ErrBox err={err} />;
  if (!data) return <div className="skel" />;
  const fronts = Object.keys(data.segments);
  const segs = ["Stronghold", "Lean", "Competitive"];
  const download = () => {
    const url = URL.createObjectURL(new Blob([csvOf(data)], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = `booths_${ac.ac}_${ac.name.replace(/\W+/g, "_")}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="panel">
      <div className="ins-hd"><h2>Booths, Lok Sabha 2024</h2><span className="muted">{data.booths} booths with votes counted {"·"} the seat was led by {BN[data.seat_leader]}</span></div>
      <p className="muted small">{data.meta.segment_rule}</p>
      <div className="ins-grid2">
        <div>
          <Table
            cols={[{ label: "Leading front", cell: (r) => <span><span className="ins-dot" style={{ background: F5[r.f].color }} />{BN[r.f]}</span> }, ...segs.map((s) => ({ label: s, n: 1, cell: (r) => data.segments[r.f][s] || 0 })), { label: "Booths", n: 1, cell: (r) => segs.reduce((a, s) => a + (data.segments[r.f][s] || 0), 0) }]}
            rows={fronts.map((f) => ({ f, key: f }))}
          />
          <p className="muted small"><b>{data.against_seat_leader}</b> of {data.booths} booths were led by a front other than the one that led the seat.</p>
          <button type="button" className="ins-more" onClick={download}>Download all {data.booths} booths (CSV)</button>
        </div>
        <div>
          <h3>Closest booths</h3>
          <Table
            cols={[
              { label: "Booth", n: 1, cell: (r) => r.ps },
              { label: "Leads", cell: (r) => BNS[BOOTH_FRONT[r.leader] || r.leader] },
              { label: "Margin", n: 1, cell: (r) => `${r.margin_pts.toFixed(1)} pts` },
              { label: "Valid votes", n: 1, cell: (r) => inr(r.votes) },
            ]}
            rows={data.competitive.slice(0, 10).map((r, i) => ({ ...r, key: i }))}
            empty="No competitive booths."
          />
        </div>
      </div>
      <p className="muted small">Booth results are official Form 20 counts. Segments describe how a booth voted, not why, and are not turnout (booth electors are not in these sheets).</p>
    </div>
  );
}

/* ============================================================ Method tab: the additional models' checks */
export function ExtraMethod({ card }) {
  const x = card && card.extra_models;
  if (!x) return null;
  const sim = x.simulator;
  const hp = sim.hindcast.pairs;
  return (
    <>
      <div className="panel">
        <h2>Additional models: what was checked</h2>
        <p className="muted small">Each model was tested on past elections before being shown. A learned model replaces a simple rule only if it clears a stated gate.</p>
        <h3>Seat watch score</h3>
        <p className="muted small">{x.watch.decision.text}</p>
        <h3>Expected turnout</h3>
        <Table
          cols={[
            { label: "Election", cell: (r) => r.v.label },
            { label: "Method used", cell: (r) => r.v.model_used },
            { label: "Ridge", n: 1, cell: (r) => `${r.v.cv_mae_pts.ridge.toFixed(2)} pts` },
            { label: "Gradient boosting", n: 1, cell: (r) => `${r.v.cv_mae_pts.gradient_boosting.toFixed(2)} pts` },
            { label: "Same as last time", n: 1, cell: (r) => `${r.v.cv_mae_pts.persistence.toFixed(2)} pts` },
            { label: "Plus statewide change", n: 1, cell: (r) => `${r.v.cv_mae_pts.persistence_plus_statewide_change.toFixed(2)} pts` },
          ]}
          rows={Object.entries(x.turnout).map(([k, v]) => ({ key: k, v }))}
        />
        <p className="muted small">Average miss with whole districts held out (lower is better). The model is used only if it beats the simple rule by at least {x.settings.turnout.promotion_margin_pts} points.</p>
        <h3>What-if simulator: given the true swing, how often is the leader right?</h3>
        <Table
          cols={[
            { label: "Election change", cell: (r) => r.k.replace("->", " to ").replaceAll("VS", "") },
            { label: "Seats called right, regional swing", n: 1, cell: (r) => `${r.v.regional_swing.seats_called_right_pct}%` },
            { label: "One statewide swing", n: 1, cell: (r) => `${r.v.statewide_swing.seats_called_right_pct}%` },
            { label: "Same winner as before", n: 1, cell: (r) => `${r.v.same_winner_as_before_pct}%` },
          ]}
          rows={Object.entries(hp).map(([k, v]) => ({ key: k, k, v }))}
        />
        <h3>Booth segments</h3>
        <p className="muted small">{x.booths.seats_covered} constituencies, {x.booths.booths ? inr(x.booths.booths) : 0} booths. {x.booths.excluded.length} constituencies left out because their sheet does not match the official totals: {x.booths.excluded.map((e) => e.ac).join(", ")}.</p>
        <h3>Limits</h3>
        <ul className="ins-list">{x.limits.map((l) => <li key={l}>{l}</li>)}</ul>
      </div>
    </>
  );
}
