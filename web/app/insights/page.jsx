"use client";

// Insights (Phase 1 models): constituency types, unusual results, expected ranges.
// Data: /api/insights/* (FastAPI router in server/insights.py, static JSON from Scripts/ml/build_insights.py).
import { useEffect, useMemo, useState } from "react";
import Header from "@/components/Header";
import { get, inr } from "@/lib/upbi";
import { ELABEL, ESHORT, FRONT, Legend, LineChart, RangeChart, RankBars, ShareBars, pct } from "@/components/insights";
import { AlliancesTab, ExtraMethod, SeatExtraPanels, TurnoutTab, WatchTab, WhatIfTab } from "@/components/insights_extra";

const TABS = [
  ["overview", "Overview"],
  ["ac", "Constituency"],
  ["watch", "Battlegrounds"],
  ["whatif", "What-if"],
  ["turnout", "Turnout"],
  ["alliances", "Alliances"],
  ["types", "Types"],
  ["surprises", "Unusual results"],
  ["method", "Method and checks"],
];
const ELECTIONS = ["VS2012", "VS2017", "VS2022", "LS2024"];
const compact = (n) => (n >= 1e7 ? `${(n / 1e7).toFixed(1)} Cr` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n));
const signed = (x, d = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(d)}%`;

function Table({ cols, rows }) {
  return (
    <div className="ins-tw">
      <table className="ins-table">
        <thead>
          <tr>{cols.map((c) => <th key={c.label} className={c.n ? "n" : ""}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.hl ? "hl" : ""}>
              {cols.map((c) => <td key={c.label} className={c.n ? "n" : c.nowrap ? "nowrap" : ""}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Strength({ s }) {
  if (s === "strong") return <span className="ins-pill crit">{"▲"} Strong outlier</span>;
  if (s === "moderate") return <span className="ins-pill warn">{"▲"} Outlier</span>;
  return <span className="ins-pill">Within the usual spread</span>;
}

function LinkBtn({ onClick, children }) {
  return <button type="button" className="ins-link" onClick={onClick}>{children}</button>;
}

/* ---------------- Overview ---------------- */
function DistrictTable({ rows }) {
  const [key, setKey] = useState("votes_2022");
  const [dir, setDir] = useState(-1);
  const [q, setQ] = useState("");
  const cols = [
    { k: "district", label: "District", v: (x) => x.district, cell: (x) => x.district },
    { k: "acs", label: "ACs", n: 1, v: (x) => x.acs, cell: (x) => x.acs },
    { k: "votes_2022", label: "Votes polled 2022", n: 1, v: (x) => x.votes_2022, cell: (x) => inr(x.votes_2022) },
    { k: "growth", label: "Change vs 2017", n: 1, v: (x) => x.growth_pct, cell: (x) => signed(x.growth_pct) },
    { k: "turnout", label: "Turnout LS 2024", n: 1, v: (x) => x.turnout_2024, cell: (x) => pct(x.turnout_2024) },
    { k: "n22", label: "BJP-led 2022", n: 1, v: (x) => x.share_2022.NDA, cell: (x) => pct(x.share_2022.NDA) },
    { k: "o22", label: "SP/INC 2022", n: 1, v: (x) => x.share_2022.OPP, cell: (x) => pct(x.share_2022.OPP) },
    { k: "b22", label: "BSP 2022", n: 1, v: (x) => x.share_2022.BSP, cell: (x) => pct(x.share_2022.BSP) },
    { k: "n24", label: "BJP-led LS 2024", n: 1, v: (x) => x.share_2024.NDA, cell: (x) => pct(x.share_2024.NDA) },
    { k: "o24", label: "SP/INC LS 2024", n: 1, v: (x) => x.share_2024.OPP, cell: (x) => pct(x.share_2024.OPP) },
    { k: "b24", label: "BSP LS 2024", n: 1, v: (x) => x.share_2024.BSP, cell: (x) => pct(x.share_2024.BSP) },
  ];
  const col = cols.find((c) => c.k === key);
  const shown = useMemo(
    () => rows.filter((x) => x.district.toLowerCase().includes(q.toLowerCase()))
      .sort((a, b) => dir * ((col.v(a) > col.v(b)) - (col.v(a) < col.v(b)))),
    [rows, q, dir, key] // eslint-disable-line react-hooks/exhaustive-deps
  );
  return (
    <>
      <div className="toolbar">
        <input type="search" placeholder="Filter districts" aria-label="Filter districts" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="ins-tw">
        <table className="ins-table">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c.k} className={c.n ? "n" : ""} aria-sort={c.k === key ? (dir < 0 ? "descending" : "ascending") : "none"}>
                  <button type="button" className="ins-th" onClick={() => { setDir(c.k === key ? -dir : c.n ? -1 : 1); setKey(c.k); }}>
                    {c.label}{c.k === key ? (dir < 0 ? " ▾" : " ▴") : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((x) => <tr key={x.district}>{cols.map((c) => <td key={c.k} className={c.n ? "n" : ""}>{c.cell(x)}</td>)}</tr>)}
          </tbody>
        </table>
      </div>
      <p className="muted small">{shown.length} of {rows.length} districts</p>
    </>
  );
}

function Tile({ label, value, delta, src }) {
  return (
    <div className="panel ins-tile">
      <div className="muted small">{label}</div>
      <div className="ins-big">{value}</div>
      <div className="muted">{delta}</div>
      <p className="muted small">Source: {src}</p>
    </div>
  );
}

function OverviewTab({ boot }) {
  const { overview: ov } = boot;
  const S = ov.state, L = ov.lists, ds = ov.districts;
  const g = S.VS2022.votes / S.VS2017.votes - 1;
  const ev = ds.reduce((a, x) => a + x.evm_votes_2024, 0);
  const el = ds.reduce((a, x) => a + x.electors_2024, 0);
  const shareRows = ELECTIONS.map((e) => ({
    label: e === "LS2024" ? "Lok Sabha 2024*" : ELABEL[e],
    sh: ["NDA", "OPP", "BSP", "OTH"].map((c) => S[e].camp_share[c]),
    extra: `Seats or segments led: BJP-led ${S[e].seats.NDA}, SP ${S[e].seats.SPF}, INC ${S[e].seats.INC}, BSP ${S[e].seats.BSP}, others ${S[e].seats.OTH}`,
  }));
  const seatRows = ELECTIONS.map((e) => ({ e, s: S[e].seats }));
  return (
    <>
      <div className="ins-grid3">
        <Tile label="Votes polled, Assembly 2022" value={compact(S.VS2022.votes)}
          delta={`${signed(g)} vs 2017 (${compact(S.VS2017.votes)})`} src="data/Uttar_Pradesh.csv, sum of AC totals" />
        <Tile label="Seats won by front, Assembly 2022" value="403 seats"
          delta={`BJP-led ${S.VS2022.seats.NDA} · SP-led ${S.VS2022.seats.SPF} · INC ${S.VS2022.seats.INC} · BSP ${S.VS2022.seats.BSP} · Others ${S.VS2022.seats.OTH}`} src="winner of each AC; allied party codes are added to their front (see Method)" />
        <Tile label="Turnout, Lok Sabha 2024" value={pct(ev / el)}
          delta="EVM votes divided by electors; postal votes excluded" src="ECI assembly-segment file for Uttar Pradesh" />
      </div>
      <div className="panel">
        <h2>Share of votes by front</h2>
        <p className="muted small">All four elections, statewide. Hover a segment for seats.</p>
        <Legend items={["NDA", "OPP", "BSP", "OTH"]} bars />
        <ShareBars rows={shareRows} aria="Statewide share of votes by front for four elections" />
        <p className="muted small">*Lok Sabha 2024 counts EVM votes only, by assembly segment. Fronts group allied party codes per election; see Method.</p>
      </div>
      <div className="panel">
        <h2>Seats by front</h2>
        <p className="muted small">Counts match the published results for 2012, 2017 and 2022.</p>
        <Table
          cols={[
            { label: "Election", cell: (r) => `${ELABEL[r.e]} (${r.e === "LS2024" ? "assembly segments led" : "seats won"})` },
            { label: "BJP-led", n: 1, cell: (r) => r.s.NDA }, { label: "SP-led", n: 1, cell: (r) => r.s.SPF },
            { label: "INC", n: 1, cell: (r) => r.s.INC }, { label: "BSP", n: 1, cell: (r) => r.s.BSP }, { label: "Others", n: 1, cell: (r) => r.s.OTH },
          ]}
          rows={seatRows}
        />
      </div>
      <div className="panel">
        <h2>Turnout by election</h2>
        <p className="muted small">Votes counted over electors, summed over the constituencies whose values passed their checks. The count is shown so a gap is visible.</p>
        <Table
          cols={[
            { label: "Election", cell: (r) => ELABEL[r.election] },
            { label: "Turnout", n: 1, cell: (r) => pct(r.turnout) },
            { label: "Constituencies with trusted data", n: 1, cell: (r) => `${r.acs} of 403` },
            { label: "Source", cell: (r) => r.source },
          ]}
          rows={ov.turnout || []}
        />
        <p className="muted small">Source: ECI booth sheets summed to constituency level (Scripts/ml/ac_booth_totals.py); 2024 from the ECI segment file</p>
      </div>
      <div className="ins-grid2">
        <div className="panel">
          <h2>Most votes polled, Assembly 2022</h2>
          <p className="muted small">Top 10 constituencies.</p>
          <RankBars aria="Top 10 constituencies by votes polled in 2022"
            rows={L.top_votes_vs2022.map((x) => ({ label: x.name, value: x.value, text: inr(x.value), what: "Votes polled", note: `${x.district} district` }))} />
        </div>
        <div className="panel">
          <h2>Biggest growth in votes polled, 2017 to 2022</h2>
          <p className="muted small">Added votes, top 10 constituencies.</p>
          <RankBars aria="Top 10 constituencies by growth in votes polled"
            rows={L.top_growth_votes.map((x) => ({ label: x.name, value: x.value, text: `+${inr(x.value)}`, what: "Added votes", note: `${x.district} district, ${signed(x.pct, 0)} vs 2017` }))} />
        </div>
      </div>
      <div className="panel">
        <h2>Districts</h2>
        <p className="muted small">Sort by any column. Votes and shares are summed from constituencies.</p>
        <DistrictTable rows={ds} />
      </div>
    </>
  );
}

/* ---------------- Constituency ---------------- */
function AcTab({ boot, acNo, setAcNo }) {
  const [ac, setAc] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    setAc(null);
    setErr("");
    get(`insights/ac/${acNo}`).then((d) => live && setAc(d)).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [acNo]);

  const optionLabel = (a) => `${a.ac} · ${a.name} (${a.district})`;
  const row = boot.acs.find((a) => a.ac === acNo);
  const label = row ? optionLabel(row) : String(acNo);
  const [text, setText] = useState(label);
  useEffect(() => setText(label), [label]);
  function commit(v) {
    const s = v.trim().toLowerCase();
    const hit = /^\d/.test(s)
      ? boot.acs.find((a) => String(a.ac) === s.split(/[^0-9]/)[0])
      : boot.acs.find((a) => a.name.toLowerCase() === s) || boot.acs.find((a) => a.name.toLowerCase().startsWith(s));
    if (hit) setAcNo(hit.ac); else setText(label);
  }
  const picker = (
    <div className="toolbar">
      <label htmlFor="ins-acq" className="muted small">Constituency</label>
      <input id="ins-acq" list="ins-acs" value={text} autoComplete="off" aria-label="Pick a constituency by number or name"
        onFocus={(e) => e.target.select()}
        onChange={(e) => { setText(e.target.value); const ex = boot.acs.find((a) => optionLabel(a) === e.target.value); if (ex) setAcNo(ex.ac); }}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") commit(e.currentTarget.value); }} />
      <datalist id="ins-acs">{boot.acs.map((a) => <option key={a.ac} value={optionLabel(a)} />)}</datalist>
    </div>
  );
  if (err) return <>{picker}<div className="panel err">Could not load this constituency: {err}</div></>;
  if (!ac) return <>{picker}<div className="skel" /></>;

  const H = ac.history;
  const TB = ac.turnout_block;
  const sur = ac.surprise;
  const lastInj = boot.card.surprise.injected_anomaly_test.slice(-1)[0];
  const histCols = [
    { label: "Election", nowrap: 1, cell: (r) => ELABEL[r.e] },
    { label: "Winner", cell: (r) => `${H[r.e].winner.name} (${H[r.e].winner.party})` },
    { label: "Margin", n: 1, cell: (r) => `${inr(H[r.e].margin_votes)} (${pct(H[r.e].margin_pp, 0)})` },
    { label: "BJP-led", n: 1, cell: (r) => pct(H[r.e].sh[0]) }, { label: "SP/INC", n: 1, cell: (r) => pct(H[r.e].sh[1]) },
    { label: "BSP", n: 1, cell: (r) => pct(H[r.e].sh[2]) }, { label: "Others", n: 1, cell: (r) => pct(H[r.e].sh[3]) },
    { label: "Votes polled", n: 1, cell: (r) => inr(H[r.e].votes) },
    { label: "Turnout", n: 1, cell: (r) => { const t = TB ? TB.turnout[r.e] : null; return t != null ? pct(t) : (H[r.e].turnout != null ? pct(H[r.e].turnout) : "n/a"); } },
  ];
  return (
    <>
      {picker}
      <div className="panel">
        <div className="ins-hd">
          <h2>{ac.name}</h2>
          <span className="muted">AC {ac.ac} {"·"} {ac.district} {"·"} {ac.reserved}</span>
        </div>
        <div className="ins-chips">
          <span className="ins-pill">Type {ac.type.id}: {ac.type.label}</span>
          {sur ? <Strength s={sur.strength} /> : <span className="ins-pill warn">Not assessed</span>}
          {ac.data_flags.map((f) => <span key={f} className="ins-pill warn">{"▲"} {f}</span>)}
        </div>
      </div>
      <div className="ins-grid2">
        <div className="panel">
          <h2>Vote share by front</h2>
          <p className="muted small">Hollow markers are the 2024 general election, a different kind of contest.</p>
          <Legend items={["NDA", "OPP", "BSP"]} />
          <LineChart ac={ac} elections={ELECTIONS} />
          {TB ? (
            <div className="ins-chips" style={{ marginTop: 10 }}>
              {["VS2017", "LS2019", "VS2022", "LS2024"].map((e) => (
                <span key={e} className="ins-pill">Turnout {ESHORT[e]}: {TB.turnout[e] != null ? pct(TB.turnout[e]) : "n/a"}</span>
              ))}
            </div>
          ) : null}
          <details>
            <summary className="muted small">Table view</summary>
            <Table cols={histCols} rows={ELECTIONS.map((e) => ({ e }))} />
            {TB ? (
              <p className="muted small">
                Electors: {["VS2017", "LS2019", "VS2022", "LS2024"].map((e) => `${ELABEL[e]} ${TB.electors[e] != null ? TB.electors[e].toLocaleString("en-IN") : "n/a"}`).join(" \u00B7 ")}.
                {" "}2017 turnout comes from the {TB.source_2017}.
              </p>
            ) : null}
          </details>
          <p className="muted small">Source: data/Uttar_Pradesh.csv (2012 to 2022) and the ECI assembly-segment file (2024)</p>
        </div>
        <div className="panel">
          <h2>If nothing changes</h2>
          {ac.expected == null ? (
            <div className="warnbox">{ac.expected_hidden || "Hidden while Compliance Mode is on."}</div>
          ) : (
            <>
              <p className="muted small">A repeat of the 2022 result, with the error seen when {"“"}same as last time{"”"} was tested on 2017 to 2022. This is not a forecast.</p>
              <RangeChart ac={ac} />
              <p className="muted small">Bar: the range 80% of constituencies landed within. Thin line: wider range that also counts 2012 to 2017. Tick: the 2022 value.</p>
            </>
          )}
        </div>
      </div>
      <div className="ins-grid2">
        <div className="panel">
          <h2>Compared with similar constituencies</h2>
          {!sur ? (
            <div className="warnbox">Not assessed: the source file is incomplete for this constituency.</div>
          ) : (
            <>
              <p className="muted small">Change from 2017 to 2022 against ACs that looked like this one before 2022.</p>
              <p>
                <Strength s={sur.strength} />{" "}
                <span className="muted small">distance from usual {sur.maxz.toFixed(1)} (flag at {boot.card.surprise.thresholds.z_flag})</span>
              </p>
              <ul className="ins-list">{sur.drivers.map((d) => <li key={d}>{d}</li>)}</ul>
              {sur.flag ? (
                <p className="muted small">
                  Common ordinary explanations to rule out first: boundary or booth changes, a candidate switch or strong independent, an alliance change,
                  a local incident, new housing or migration. A flag is a statistical outlier, not evidence of anything improper.
                </p>
              ) : null}
              {lastInj ? (
                <p className="muted small">
                  Limit: in tests this check found {Math.round(lastInj.recall * 100)}% of artificial {lastInj.shift_pts}-point shifts, so it only catches large departures.
                </p>
              ) : (
                <p className="muted small">Limit: this check only catches large departures from similar constituencies. The planted-shift test was not run for this build (quick mode).</p>
              )}
            </>
          )}
        </div>
        <div className="panel">
          <h2>Constituencies with a similar vote history</h2>
          <p className="muted small">Nearest five across all four elections.</p>
          <ul className="ins-look">
            {ac.look_alikes.map((l) => {
              const o = boot.acs.find((a) => a.ac === l.ac);
              return (
                <li key={l.ac}>
                  <LinkBtn onClick={() => setAcNo(l.ac)}>{l.name}</LinkBtn>
                  <span className="muted small">{o ? `${o.district} · Type ${o.type}` : ""}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
      <SeatExtraPanels ac={ac} boot={boot} />
    </>
  );
}

/* ---------------- Types ---------------- */
function TypesTab({ boot, openAc }) {
  const [open, setOpen] = useState(null);
  const ch = boot.card.typology;
  const byAc = useMemo(() => new Map(boot.acs.map((a) => [a.ac, a])), [boot.acs]);
  const shares = (t, y) => {
    const m = t.mean_shares[y];
    const three = [m.NDA, m.OPP, m.BSP];
    return [...three, Math.max(0, 1 - three.reduce((a, b) => a + b, 0))];
  };
  const members = open == null ? null : boot.types.find((t) => t.id === open);
  return (
    <>
      <div className="panel">
        <h2>Constituency types</h2>
        <p className="muted small">Groups of constituencies with a similar vote history across the four elections. Names are written by rule from average shares, so a person should review them.</p>
        <Legend items={["NDA", "OPP", "BSP", "OTH"]} bars />
        <p className="muted small">
          How solid are the groups? Silhouette {ch.chosen.silhouette} (1 is perfectly separate) and stability {ch.chosen.stability_ari_mean} (1 is identical on resampling).
          Constituencies form a continuum, so these are slices of it, not natural clusters.
        </p>
      </div>
      <div className="ins-grid2">
        {boot.types.map((t) => (
          <div className="panel" key={t.id}>
            <div className="ins-hd"><h3>Type {t.id}</h3><span className="muted">{t.size} constituencies</span></div>
            <p><b>{t.label}</b></p>
            <ShareBars rowH={28} thick={16} labelW={56} W={380} aria={`Average vote shares for type ${t.id}`}
              rows={[{ label: "2022", sh: shares(t, "VS2022") }, { label: "LS 2024", sh: shares(t, "LS2024") }]} />
            <p className="muted small">Typical: {t.typical_acs.map((a) => byAc.get(a)?.name).join(", ")}</p>
            <p className="muted small">{t.flagged} flagged as unusual</p>
            <LinkBtn onClick={() => setOpen(open === t.id ? null : t.id)}>{open === t.id ? "Hide members" : "Show members"}</LinkBtn>
          </div>
        ))}
      </div>
      {members ? (
        <div className="panel">
          <h2>Type {members.id}: {members.label}</h2>
          <p className="muted small">{members.size} constituencies</p>
          <Table
            cols={[
              { label: "AC", n: 1, cell: (a) => a.ac },
              { label: "Constituency", cell: (a) => <LinkBtn onClick={() => openAc(a.ac)}>{a.name}</LinkBtn> },
              { label: "District", cell: (a) => a.district },
            ]}
            rows={members.members.map((n) => byAc.get(n)).filter(Boolean)}
          />
        </div>
      ) : null}
    </>
  );
}

/* ---------------- Unusual results ---------------- */
function SurprisesTab({ boot, openAc }) {
  const T = boot.card.surprise;
  return (
    <>
      <div className="panel">
        <h2>Unusual results, Assembly 2017 to 2022</h2>
        <p className="muted small">
          {boot.surprises.length} of {boot.acs.filter((a) => a.clean).length} constituencies changed very differently from ACs that looked like them before 2022.
          These are statistical outliers, listed so a person can check the ordinary explanations first.
        </p>
        <Table
          cols={[
            { label: "Constituency", cell: (a) => <LinkBtn onClick={() => openAc(a.ac)}>{a.name}</LinkBtn> },
            { label: "District", cell: (a) => a.district },
            { label: "Type", nowrap: 1, cell: (a) => `Type ${a.type}` },
            { label: "Reading", nowrap: 1, cell: (a) => <Strength s={a.strength} /> },
            { label: "Distance from usual", n: 1, cell: (a) => a.maxz.toFixed(1) },
            { label: "What stands out", cell: (a) => a.drivers[0] },
          ]}
          rows={boot.surprises}
        />
        <p className="muted small">
          Rule: distance of {T.thresholds.z_flag} or more with Isolation Forest agreeing, or {T.thresholds.z_extreme} or more on its own.
          Peers are the {T.thresholds.peers} constituencies most similar on 2012 and 2017 results.
        </p>
      </div>
      <div className="panel">
        <h2>How well does the check work?</h2>
        <p className="muted small">We shifted the BJP-led share of 20 random constituencies by a known amount and counted how many were flagged, over 10 repeats.</p>
        <div className="ins-narrow">
          <Table
            cols={[
              { label: "Artificial shift", n: 1, cell: (r) => `${r.shift_pts} pts` },
              { label: "Flagged", n: 1, cell: (r) => `${Math.round(r.recall * 100)}%` },
              { label: "Other constituencies flagged", n: 1, cell: (r) => `${(r.false_flag_rate * 100).toFixed(1)}%` },
            ]}
            rows={T.injected_anomaly_test}
          />
        </div>
        <p className="muted small">
          The target in the plan was 80% found at 2% false flags. This first version does not reach it: ordinary variation between elections is large,
          so only big departures stand out. A better version would compare several parties together and use district trends.
        </p>
      </div>
    </>
  );
}

/* ---------------- Method ---------------- */
function CoverageCards({ cov }) {
  if (!cov) return null;
  const reader = { main: "standard reader", generic: "label-based reader", form20_preamble: "Form 20 preamble" };
  const c = cov.checks;
  return (
    <>
      <div className="panel">
        <h2>Data cleaning: what was read</h2>
        <p className="muted small">{cov.note}</p>
        <Table
          cols={[
            { label: "Source", cell: (r) => r.label },
            { label: "Files", n: 1, cell: (r) => r.files },
            { label: "Constituencies read", n: 1, cell: (r) => `${r.first_run.read} \u2192 ${r.acs_read}` },
            { label: "Turnout passed its checks", n: 1, cell: (r) => `${r.first_run.trusted_turnout} \u2192 ${r.trusted_turnout}` },
            { label: "Read by", cell: (r) => Object.entries(r.readers).map(([k, v]) => `${reader[k] || k} ${v}`).join(", ") },
          ]}
          rows={cov.by_election}
        />
        <p className="muted small">Left of each arrow is the first run, right is now, out of 403 constituencies. {cov.filled}</p>
      </div>
      <div className="ins-grid2">
        <div className="panel">
          <h2>Still unread, and why</h2>
          <ul className="ins-list">
            {cov.by_election.flatMap((e) => e.unread.map((u) => (
              <li key={`${e.election}-${u.reason}`}><b>{e.label}, {u.files.length} file{u.files.length > 1 ? "s" : ""}.</b> {u.reason} ({u.files.join(", ")}).</li>
            )))}
          </ul>
        </div>
        <div className="panel">
          <h2>Checks against official results</h2>
          <ul className="ins-list">
            <li><b>Assembly 2017.</b> {c.vs2017_votes_vs_official.within_range} of {c.vs2017_votes_vs_official.compared} constituencies are within 4% of the official vote total (median {(c.vs2017_votes_vs_official.median_ratio * 100).toFixed(1)}%; the gap is postal ballots).</li>
            <li><b>Assembly 2022.</b> {c.vs2022_votes_vs_official.within_range} of {c.vs2022_votes_vs_official.compared} are within 4% (median {(c.vs2022_votes_vs_official.median_ratio * 100).toFixed(1)}%).</li>
            <li><b>Lok Sabha 2019.</b> {c.ls2019_seats_vs_official.both_within_tol} of {c.ls2019_seats_vs_official.complete_pcs} complete parliamentary seats match the official EVM votes on total and BJP votes. Party shares are used only for the {c.ls2019_constituencies_in_verified_seats} constituencies in verified seats.</li>
          </ul>
        </div>
      </div>
    </>
  );
}

function MethodTab({ boot }) {
  const { card, meta } = boot;
  const k = card.data_checks, T = card.typology, B = card.baseline, Lr = card.learned_forecaster_vs_baseline;
  const seats = k.seats_by_camp;
  const ov = k.alliance_overlap_acs;
  const cov = card.data_coverage;
  const missingTurnout = (e) => 403 - cov.by_election.find((x) => x.election === e).trusted_turnout;
  return (
    <>
      <div className="panel">
        <h2>How the numbers get here</h2>
        <ol className="ins-steps">
          <li><b>Public results</b>Assembly 2012, 2017, 2022 and Lok Sabha 2024 by assembly segment, for all 403 constituencies.</li>
          <li><b>Fronts</b>Allied party codes are added together per election, so an Apna Dal (S) seat is not shown as {"“"}BJP 0%{"”"}.</li>
          <li><b>Three models</b>Types (k-means), unusual results (robust z-score plus Isolation Forest), and an expected range from {"“"}same as last time{"”"}.</li>
          <li><b>This page</b>Results are computed once in a batch and read here. Data version {meta.data_version}, model {meta.model_version}.</li>
        </ol>
      </div>
      <CoverageCards cov={card.data_coverage} />
      <div className="ins-grid2">
        <div className="panel">
          <h2>Checks that ran</h2>
          <ul className="ins-list">
            <li><b>All four elections cover 403 constituencies.</b></li>
            <li><b>Seat counts match published results.</b> 2012: BJP {seats.VS2012.NDA}, SP {seats.VS2012.SPF}, BSP {seats.VS2012.BSP}. 2017: BJP-led {seats.VS2017.NDA}, SP+INC {seats.VS2017.SPF}, BSP {seats.VS2017.BSP}. 2022: BJP-led {seats.VS2022.NDA}, SP-led {seats.VS2022.SPF}.</li>
            <li><b>{k.excluded_from_fitting.length} constituencies are kept out of model fitting.</b> Their 2012 rows cover only 45% to 55% of votes polled in the source file: AC {k.excluded_from_fitting.join(", ")}.</li>
            <li><b>Only Uttar Pradesh rows are used from the 2024 file.</b> A loose match on {"“"}Uttar{"”"} also pulls in Uttarakhand, whose AC numbers 1 to 70 collide with ours; the build uses an exact match and checks for 4,288 candidate rows.</li>
            <li><b>Allies rarely stand against their front leader.</b> Constituencies where two codes of one front both stood: 2017 {ov.VS2017.NDA || 0} (BJP-led) and {ov.VS2017.SPF || 0} (SP+INC friendly contests); 2022 {ov.VS2022.NDA || 0} (BJP-led); 2024 {ov.LS2024.NDA || 0}.</li>
            <li><b>Constituency names agree between files.</b> {Math.round(k.ac_name_match_rate_ls2024_vs_config * 100)}% match exactly; the rest are spelling variants such as Bagpat and Baghpat.</li>
          </ul>
        </div>
        <div className="panel">
          <h2>What is not here</h2>
          <ul className="ins-list">
            <li><b>Booth-level results.</b> The match of booths across elections has not passed its check yet.</li>
            <li><b>News, sentiment or predictions of 2027.</b> Those are later phases and need data this repository does not have.</li>
            <li><b>Turnout for every constituency.</b> {cov ? `${missingTurnout("VS2022")} have no trusted 2022 value and ${missingTurnout("LS2019")} no trusted 2019 value` : "Some constituencies have no trusted value"} (see Data cleaning above). Missing values stay blank.</li>
            <li><b>Reasons people vote.</b> Types and flags describe results only.</li>
          </ul>
        </div>
      </div>
      <div className="panel">
        <h2>Choosing the number of types</h2>
        <p className="muted small">History reduced to {T.pca_components} main directions ({Math.round(T.pca_variance_explained * 100)}% of the variation kept), then k-means. The highlighted row was chosen.</p>
        <div className="ins-narrow">
          <Table
            cols={[
              { label: "Types", n: 1, cell: (r) => r.k },
              { label: "Silhouette", n: 1, cell: (r) => r.silhouette.toFixed(3) },
              { label: "Stability (mean)", n: 1, cell: (r) => r.stability_ari_mean.toFixed(3) },
              { label: "Smallest group", n: 1, cell: (r) => r.smallest_group },
              { label: "Score", n: 1, cell: (r) => `${r.k === T.chosen_k ? "✔ " : ""}${r.score.toFixed(3)}` },
            ]}
            rows={T.selection.map((r) => ({ ...r, hl: r.k === T.chosen_k }))}
          />
        </div>
      </div>
      <div className="panel">
        <h2>Does a learned model beat {"“"}same as last time{"”"}?</h2>
        <p className="muted small">
          Learned on the {Lr.train_transition[0].slice(2)} to {Lr.train_transition[1].slice(2)} change, tested on {Lr.test_transition[0].slice(2)} to {Lr.test_transition[1].slice(2)}.
          Error is the average miss in percentage points; lower is better.
        </p>
        <Table
          cols={[
            { label: "Front", cell: (r) => FRONT[r.camp].name },
            { label: "Method", cell: (r) => r.method },
            { label: "Average miss", n: 1, cell: (r) => r.mae_pts.toFixed(1) },
            { label: "80% within", n: 1, cell: (r) => r.within_80pct_pts.toFixed(1) },
          ]}
          rows={Lr.rows.map((r) => ({ ...r, hl: r.method.startsWith("Same") }))}
        />
        <p className="muted small">{Lr.decision}. The learned models did better for BSP but worse for the BJP-led front, and there is only one test transition, so the simple baseline stays.</p>
      </div>
      <div className="panel">
        <h2>Expected-range bands</h2>
        <p className="muted small">Half-width of the range within which 80% of constituencies landed when {"“"}same as last time{"”"} was tested.</p>
        <div className="ins-narrow">
          <Table
            cols={[
              { label: "Front", cell: (r) => FRONT[r.c].name },
              { label: "Usual band (2017 to 2022)", n: 1, cell: (r) => `±${(r.b.band_last * 100).toFixed(1)} pts` },
              { label: "Wide band (adds 2012 to 2017)", n: 1, cell: (r) => `±${(r.b.band_pooled * 100).toFixed(1)} pts` },
            ]}
            rows={Object.entries(B.bands).map(([c, b]) => ({ c, b }))}
          />
        </div>
        <p className="muted small">The wide band for the BJP-led front is large because its vote share jumped by about 24 points between 2012 and 2017.</p>
      </div>
      <div className="panel">
        <h2>Limits</h2>
        <ul className="ins-list">{card.limits.map((l) => <li key={l}>{l}</li>)}</ul>
      </div>
    </>
  );
}

/* ---------------- page ---------------- */
export default function InsightsPage({ searchParams }) {
  const [tab, setTab] = useState(TABS.some((t) => t[0] === searchParams?.tab) ? searchParams.tab : "overview");
  const [acNo, setAcNo] = useState(Number(searchParams?.ac) || 86);
  const [boot, setBoot] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([get("insights/meta"), get("insights/overview"), get("insights/types"), get("insights/acs"), get("insights/surprises"), get("insights/card")])
      .then(([meta, overview, types, acs, sur, card]) => setBoot({ meta, overview, types: types.types, acs: acs.rows, surprises: sur.rows, card }))
      .catch((e) => setErr(e.message));
  }, []);

  useEffect(() => { // keep the address shareable
    const p = new URLSearchParams({ tab });
    if (tab === "ac") p.set("ac", String(acNo));
    window.history.replaceState(null, "", `/insights?${p}`);
  }, [tab, acNo]);

  const openAc = (n) => {
    setAcNo(n);
    setTab("ac");
    window.scrollTo({ top: 0 });
  };

  return (
    <>
      <Header hideSelectors />
      <main className="wrap">
        <div className="warnbox">
          <b>What this is.</b> Constituency results (assembly 2012, 2017, 2022 and Lok Sabha 2024 by assembly segment) turned into types, unusual-result flags, expected ranges,
          a seat watch list, a what-if calculator, expected turnout, alliance estimates and 2024 booth segments. There is no news, no poll and no forecast of who will win:
          where a number looks ahead, it is a calculator or a ranking, and it says how well the same method worked in the past.
        </div>
        {boot && boot.meta.compliance_mode === "on" ? (
          <div className="warnbox"><b>Compliance Mode is on.</b> Forward-looking numbers are hidden.</div>
        ) : null}
        <div className="tabs" role="tablist" aria-label="Insights sections">
          {TABS.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        {err ? (
          <div className="panel err">Insights unavailable: {err}</div>
        ) : !boot ? (
          <div className="skel" />
        ) : tab === "overview" ? (
          <OverviewTab boot={boot} />
        ) : tab === "ac" ? (
          <AcTab boot={boot} acNo={acNo} setAcNo={setAcNo} />
        ) : tab === "watch" ? (
          <WatchTab openAc={openAc} />
        ) : tab === "whatif" ? (
          <WhatIfTab openAc={openAc} />
        ) : tab === "turnout" ? (
          <TurnoutTab openAc={openAc} />
        ) : tab === "alliances" ? (
          <AlliancesTab />
        ) : tab === "types" ? (
          <TypesTab boot={boot} openAc={openAc} />
        ) : tab === "surprises" ? (
          <SurprisesTab boot={boot} openAc={openAc} />
        ) : (
          <>
            <MethodTab boot={boot} />
            <ExtraMethod card={boot.card} />
          </>
        )}
        <footer className="site">Data version {boot ? boot.meta.data_version : "…"} {"·"} public election results, constituency level.</footer>
      </main>
    </>
  );
}
