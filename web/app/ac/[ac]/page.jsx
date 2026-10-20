"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Header from "@/components/Header";
import { PartyBars, SexPie } from "@/components/charts";
import { PartyChooser } from "@/components/PartyPicker";
import { ELECTIONS, YR, ZONES, RELS, RELABEL, get, inr, isBadParty, loadError, useParty, withParty, zclass } from "@/lib/upbi";

const GROUPS = {
  results: ["ps", "name", "zone", "avg_diff", "latest_diff", "party_b", "a2017", "b2017", "d2017", "a2019", "b2019", "d2019", "a2022", "b2022", "d2022", "a2024", "b2024", "d2024"],
  turnout: ["ps", "name", "e2017", "m2017", "f2017", "o2017", "t2017", "to2017", "e2019", "m2019", "f2019", "o2019", "t2019", "to2019", "e2022", "m2022", "f2022", "o2022", "t2022", "to2022", "t2024", "ac_electors_2024"],
  religion: null,
};
const COLHDR = { ps: "PS", name: "Booth", zone: "Zone", avg_diff: "Avg Δ", latest_diff: "Latest Δ", party_b: "Opponent", ac_electors_2024: "2024 AC electors" };

function hdr(c, party) {
  if (COLHDR[c]) return COLHDR[c];
  const m = c.match(/^([abdt]|e|m|f|o|t|to)(\d{4})$/);
  if (m) return { a: `${party || "Party"}% `, b: "Opp% ", d: "Δ ", e: "E", m: "M", f: "F", o: "O", t: "T", to: "TO%" }[m[1]] + m[2];
  return c.replace(/_17$/, "").replace(/_/g, " ") + " (modeled)";
}
function cell(c, r, onPs) {
  if (c === "zone")
    return (
      <span className={`zone ${zclass(r.zone)}`}>{r.zone || "—"}</span>
    );
  if (c === "ps")
    return (
      <a href="#" onClick={(e) => { e.preventDefault(); onPs && onPs(r.ps); }}>
        {r.ps}
      </a>
    );
  if (c === "name") return String(r.name || "").slice(0, 42);
  const v = r[c];
  if (v == null || v === "") return <span className="muted">—</span>;
  if (/^b(2017|2019|2022|2024)$/.test(c)) {
    // the opponent's share; where the usual opponent did not stand that year, the strongest other party is shown by name
    const o = r["opp" + c.slice(1)];
    const txt = `${(v * 100).toFixed(1)}%`;
    return o && r.party_b && o !== r.party_b ? `${txt} (${o})` : txt;
  }
  if (/^[abd](2017|2019|2022|2024)$/.test(c) || /^(avg_diff|latest_diff|to\d{4})$/.test(c))
    return `${(v * 100).toFixed(1)}%`;
  if (/_percent/.test(c)) return `${Number(v).toFixed(1)}%`;
  if (/^age_/.test(c)) return `${Number(v).toFixed(1)} yrs`;
  if (c === "electors_17") return inr(v);
  return String(v);
}

export default function ACPage({ params }) {
  const ac = params.ac;
  const [election, setElection] = useState("LS2024");
  const [vs, setVs] = useState("VS2022");
  const [tab, setTab] = useState("overview");
  const [head, setHead] = useState(null);
  const [meta, setMeta] = useState(null);
  const [err, setErr] = useState("");
  const [party, setParty, ready] = useParty();

  useEffect(() => {
    get("meta")
      .then(setMeta)
      .catch((e) => setErr(e.message));
  }, []);
  const parties = meta ? meta.parties || [] : null;
  useEffect(() => {
    if (ready && !party && parties && parties.length === 1) setParty(parties[0]);
  }, [ready, party, parties, setParty]);

  useEffect(() => {
    if (!ready) return;
    setErr("");
    // the seat's zone badge is the chosen party's; without a party only the party-neutral parts are shown
    Promise.all([get("acs"), party ? get(`overview?election=${election}&vs=${vs}&party=${party}`) : Promise.resolve(null)])
      .then(([info, o]) => {
        const mine = info.rows.filter((r) => String(r.ac) === String(ac));
        if (!mine.length) throw new Error(`AC ${ac} not in store.`);
        setHead({
          name: mine[0].ac_name,
          dist: mine[0].district,
          rows: mine,
          zone: (o && o.ac_zone && (o.ac_zone[String(ac)] || o.ac_zone[ac])) || "",
        });
      })
      .catch((e) => (isBadParty(e) ? setParty(null) : setErr(e.message)));
  }, [ac, election, vs, party, ready, setParty]);

  return (
    <>
      <Header election={election} vs={vs} onElection={setElection} onVs={setVs} parties={parties} party={party} onParty={setParty} />
      <main className="wrap">
        {party ? (
          <div className="warnbox">
            <b>Booth analysis from {party}&apos;s side.</b> Booth shares, zones and the &quot;Opponent&quot; comparison here are {party}&apos;s against its strongest opponent in each booth. Switch party with the buttons above. For all parties side by side, use <Link href="/insights">Insights</Link>.
          </div>
        ) : null}
        {err ? (
          <div className="panel err">{loadError(err)}</div>
        ) : !head ? (
          <div className="skel" />
        ) : (
          <div className="panel">
            <h2>
              <Link href={withParty("/booths", party)} className="backbtn" title="back to booth dashboard">
                ←
              </Link>{" "}
              {head.name}{" "}
              <span className="muted">
                ({head.dist} · AC {ac})
              </span>{" "}
              {party ? <span className={`zone ${zclass(head.zone)}`}>{head.zone}</span> : null}
            </h2>
            <div className="tabs">
              {[
                ["overview", "Overview"],
                ["booths", "Booths"],
                ["past", "Past Elections"],
                ["map", "Map"],
              ].map(([t, l]) => (
                <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>
                  {l}
                </button>
              ))}
            </div>
            {tab === "overview" && <OverviewTab ac={ac} />}
            {tab === "booths" && (party ? <BoothsTab ac={ac} party={party} /> : <PartyChooser parties={parties} onParty={setParty} what="the booths of this constituency" />)}
            {tab === "past" && <PastTab ac={ac} party={party} />}
            {tab === "map" && (
              <p className="muted">
                Booth map arrives in the geo phase (AC polygons → geocoded booths → Voronoi).
                Until then, zones and tables are the schematic stand-in.
              </p>
            )}
          </div>
        )}
      </main>
    </>
  );
}

function OverviewTab({ ac }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    Promise.all([
      get(`ac/${ac}/sexratio`),
      get(`ac/${ac}/religion`),
      get(`ac/${ac}/ages`),
      get(`ac/${ac}/averages`),
      ...ELECTIONS.map((eid) => get(`ac/${ac}/votes?election=${eid}`)),
    ])
      .then(([sex, rel, ages, avg, ...votes]) => setData({ sex, rel, ages, avg, votes }))
      .catch(() => setData({ error: true }));
  }, [ac]);
  if (!data) return <span className="muted">loading…</span>;
  if (data.error) return <span className="err">failed to load</span>;
  return (
    <>
      <h3>Male–female turnout</h3>
      {data.sex.rows.length ? <SexPie rows={data.sex.rows} /> : <span className="muted">no data</span>}
      <h3>
        Religion-wise mix (AC, Estimated){" "}
        <span className="muted small">
          {data.rel.with_data} of {data.rel.booths} booths
        </span>
      </h3>
      {RELS.map((r) => (
        <div className="relrow" key={r}>
          <span>
            {RELABEL[r]}
          </span>
          <span className="reltrack">
            <i style={{ width: `${Math.min(100, data.rel.religion[r] || 0)}%`, background: "#5b6b7c" }} />
          </span>
          <b>{data.rel.religion[r] != null ? `${data.rel.religion[r].toFixed(1)}%` : "—"}</b>
        </div>
      ))}
      <p className="small muted">Model estimates from 2017-roll names, not counted people.</p>
      <h3>
        Age profile <span className="muted small">(modeled, 2017 roll{data.ages.overall.mean != null ? ` · mean ${data.ages.overall.mean} yrs ± ${data.ages.overall.sd}` : ""})</span>
      </h3>
      <table className="data">
        <thead>
          <tr>
            <th>Group</th>
            <th>Mean age</th>
            <th>SD</th>
            <th>Modeled electors</th>
          </tr>
        </thead>
        <tbody>
          {["hindu", "muslim", "christian", "sikh", "jain", "buddhist", "parsi"].map((r) => {
            const g = data.ages.by_religion[r] || {};
            return (
              <tr key={r}>
                <td>{RELABEL[r]}</td>
                <td>{g.mean != null ? `${g.mean} yrs` : "—"}</td>
                <td>{g.sd != null ? g.sd : "—"}</td>
                <td>{g.electors ? inr(g.electors) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <h3>Per-booth averages</h3>
      <table className="data">
        <thead>
          <tr>
            <th>Election</th>
            <th>Booths</th>
            <th>Avg electors</th>
            <th>Avg male</th>
            <th>Avg female</th>
            <th>Avg polled</th>
          </tr>
        </thead>
        <tbody>
          {data.avg.rows.map((r) => (
            <tr key={r.election}>
              <td>{YR[r.election]}</td>
              <td>{inr(r.booths)}</td>
              <td>{inr(r.avg_electors)}</td>
              <td>{inr(r.avg_male)}</td>
              <td>{inr(r.avg_female)}</td>
              <td>{inr(r.avg_polled)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {ELECTIONS.map((eid, i) => {
        const p = data.votes[i].parties.filter((x) => x.party !== "NOTA").slice(0, 6);
        return (
          <div key={eid}>
            <h3>
              {YR[eid]} top parties{" "}
              {data.votes[i].source && <span className="muted small">({data.votes[i].source})</span>}
            </h3>
            {p.length ? <PartyBars items={p.map((x) => [x.party, x.votes])} /> : <span className="muted">no data</span>}
          </div>
        );
      })}
    </>
  );
}

function BoothsTab({ ac, party }) {
  const [f, setF] = useState({ zone: "", q: "", opponent: "", sort: "ps", order: "asc", page: 1, group: "results" });
  const [d, setD] = useState(null);
  const [demoCols, setDemoCols] = useState([]);
  const [sel, setSel] = useState(null);
  const cols = f.group === "religion" ? ["ps", "name", ...demoCols] : GROUPS[f.group];

  useEffect(() => {
    const p = new URLSearchParams({ ac, party, page: f.page, sort: f.sort, order: f.order });
    if (f.zone) p.set("zone", f.zone);
    if (f.q) p.set("q", f.q);
    if (f.opponent) p.set("opponent", f.opponent);
    get(`booths?${p}`)
      .then((res) => {
        setD(res);
        if (res.demo_cols) {
          setDemoCols(res.demo_cols);
          GROUPS.religion = ["ps", "name", ...res.demo_cols];
        }
      })
      .catch(() => setD({ error: true }));
  }, [ac, f, party]);

  const pages = d && !d.error ? Math.max(1, Math.ceil(d.total / d.page_size)) : 1;
  return (
    <>
      <div className="warnbox">
        Religion shares are <b>model estimates from voter names</b>. Blank = suppressed or no data.
      </div>
      <div className="toolbar">
        <input placeholder="search booth name/PS…" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value, page: 1 })} />
        <select value={f.zone} onChange={(e) => setF({ ...f, zone: e.target.value, page: 1 })}>
          <option value="">all zones</option>
          {ZONES.map((z) => (
            <option key={z}>{z}</option>
          ))}
        </select>
        <input placeholder="Opponent =" style={{ width: 110 }} value={f.opponent} onChange={(e) => setF({ ...f, opponent: e.target.value, page: 1 })} />
        <select value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value, page: 1 })}>
          <option value="ps">PS</option>
          <option value="avg_diff">avg Δ</option>
          <option value="latest_diff">latest Δ</option>
          <option value="party_b">Opponent</option>
        </select>
        <span className="cols">
          {[["results", "Results"], ["turnout", "Turnout"], ["religion", "Religion-wise"]].map(([g, lbl]) => (
            <button key={g} className={f.group === g ? "on" : ""} onClick={() => setF({ ...f, group: g })}>
              {lbl}
            </button>
          ))}
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>
                  <a
                    href="#"
                    onClick={(e) => {
                      e.preventDefault();
                      setF(f.sort === c ? { ...f, order: f.order === "asc" ? "desc" : "asc" } : { ...f, sort: c, order: "asc" });
                    }}
                    style={{ color: "inherit" }}
                  >
                    {hdr(c, party)}
                    {f.sort === c ? (f.order === "asc" ? " ▲" : " ▼") : ""}
                  </a>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!d ? (
              <tr><td className="muted">loading…</td></tr>
            ) : d.error ? (
              <tr><td className="err">failed to load</td></tr>
            ) : (
              d.rows.map((r, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c}>{cell(c, r, setSel)}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {f.group === "results" && (
        <p className="small muted">
          {party}% is {party}&apos;s share of the votes polled in the booth; Opp% is its Opponent&apos;s share. Where the Opponent did not stand in an
          election (an ally took the seat), the strongest other party that year is used and named in brackets. A dash means no usable figure: the
          party did not stand, or the booth&apos;s turnout figure could not be right.
        </p>
      )}
      <div className="pager">
        <button onClick={() => f.page > 1 && setF({ ...f, page: f.page - 1 })}>← prev</button>
        <span>{d && !d.error ? `${inr(d.total)} booths · page ${d.page} / ${inr(pages)}` : ""}</span>
        <button onClick={() => setF({ ...f, page: f.page + 1 })}>next →</button>
      </div>
      {sel && <BoothDrawer ac={ac} ps={sel} party={party} onClose={() => setSel(null)} />}
    </>
  );
}

function BoothDrawer({ ac, ps, party, onClose }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    get(`booth/${ac}/${encodeURIComponent(ps)}?party=${party}`)
      .then(setD)
      .catch(() => setD({ error: true }));
  }, [ac, ps, party]);
  return (
    <div className="drawer">
      <b>
        AC {ac} · PS {ps}
      </b>{" "}
      <button onClick={onClose} style={{ float: "right" }}>
        close ✕
      </button>
      {!d ? (
        <span className="muted">loading…</span>
      ) : d.error ? (
        <span className="err">failed to load</span>
      ) : (
        ELECTIONS.map((eid) => {
          const e = (d.elections || []).find((x) => x.election === eid);
          const v = (d.votes[eid] || []).filter((x) => x.party !== "NOTA").slice(0, 8);
          return (
            <div key={eid}>
              <h3>
                {YR[eid]}{" "}
                {e
                  ? `— polled ${inr(e.polled)} · electors ${e.electors ?? "—"} · M/F/O ${e.male ?? "—"}/${e.female ?? "—"}/${e.other ?? "—"}`
                  : "— no data"}
              </h3>
              {v.length ? <PartyBars items={v.map((x) => [`${x.party} · ${String(x.candidate).slice(0, 26)}`, x.votes])} /> : null}
            </div>
          );
        })
      )}
    </div>
  );
}

function PastTab({ ac, party }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    get(`ac/${ac}/past${party ? `?party=${party}` : ""}`)
      .then(setD)
      .catch(() => setD({ error: true }));
  }, [ac, party]);
  if (!d) return <span className="muted">loading…</span>;
  if (d.error) return <span className="err">failed to load</span>;
  return (
    <>
      <table className="data">
        <thead>
          <tr>
            <th>Election</th>
            <th>Electors</th>
            <th>Polled</th>
            <th>Turnout</th>
            {party ? <th>{party} votes</th> : null}
            {party ? <th>{party} share</th> : null}
            <th>Winner</th>
            <th>Runner-up</th>
            <th>Margin</th>
          </tr>
        </thead>
        <tbody>
          {d.rows.map((r) => (
            <tr key={r.election}>
              <td>{YR[r.election]}</td>
              <td>{r.turnout.electors != null ? inr(r.turnout.electors) : "—"}</td>
              <td>{r.turnout.polled != null ? inr(r.turnout.polled) : "—"}</td>
              <td>{r.turnout.turnout != null ? `${r.turnout.turnout}%` : "—"}</td>
              {party ? <td>{r.party_votes ? inr(r.party_votes) : "—"}</td> : null}
              {party ? <td>{r.party_share != null && r.party_votes ? `${r.party_share}%` : "—"}</td> : null}
              <td>{r.winner || "—"}</td>
              <td>{r.runnerup || "—"}</td>
              <td>
                {r.margin_votes != null ? `${inr(r.margin_votes)} (${r.margin_pp}pp)` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted">
        Winner = most votes; 2024 rows come from official segment totals, earlier years from converted booths.
      </p>
    </>
  );
}
