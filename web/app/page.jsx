"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Header from "@/components/Header";
import { Donut, Gauge, TrendChart } from "@/components/charts";
import {
  API_IMG,
  YR,
  ZGLYPH,
  RELS,
  RELABEL,
  RELCOLOR,
  get,
  inr,
  pct1,
  zclass,
} from "@/lib/upbi";

function Delta({ cur, prev }) {
  if (cur == null || prev == null) return <span className="muted">—</span>;
  const d = cur - prev;
  return (
    <span className={d >= 0 ? "up" : "down"}>
      {d >= 0 ? "▲" : "▼"} {Math.abs(d).toFixed(1)}pp
    </span>
  );
}

export default function Home() {
  const [election, setElection] = useState("LS2024");
  const [vs, setVs] = useState("VS2022");
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setD(null);
    setErr("");
    Promise.all([
      get(`overview?election=${election}&vs=${vs}`),
      get("meta"),
      get("acs"),
      get("trend"),
    ])
      .then(([o, meta, acs, trend]) => setD({ o, meta, acs, trend }))
      .catch((e) => setErr(e.message));
  }, [election, vs]);

  return (
    <>
      <Header election={election} vs={vs} onElection={setElection} onVs={setVs} />
      <main className="wrap">
        {err ? (
          <div className="panel err">
            API unreachable: {err} (is the FastAPI server running? See web/README.)
          </div>
        ) : !d ? (
          <>
            <div className="skel" />
            <div className="skel" />
          </>
        ) : (
          <Dashboard d={d} election={election} vs={vs} />
        )}
      </main>
      <footer className="wrap site">
        Booth-level aggregates from ECI records · religion columns are <b>modeled estimates</b> ·
        outlier flags are statistical, never fraud claims · formulas in{" "}
        <code>server/DASHBOARD_LOGIC.md</code>
        {d && d.meta && (
          <>
            {" "}· store built {d.meta.built_at || "unknown"}
            {d.meta.store_ok === false && <b className="err"> · INCOMPLETE STORE — rebuild</b>}
          </>
        )}
      </footer>
    </>
  );
}

function Dashboard({ d, election, vs }) {
  const { o, meta, acs, trend } = d;
  const isLS = election.startsWith("LS");
  const bjp = o.seats.find((s) => s.party === "BJP");
  const bjpSeats = bjp ? bjp.seats : 0;
  const seatPct = o.seats_counted ? (100 * bjpSeats) / o.seats_counted : 0;
  const dShare = o.avg_share != null && o.avg_share_vs != null ? o.avg_share - o.avg_share_vs : null;
  const acTotal = o.ac_zones.reduce((a, x) => a + x.acs, 0);
  const boothTotal = o.booth_zones.reduce((a, x) => a + x.booths, 0);

  const points = d.trend.rows.map((t) => ({
    label: YR[t.election] + (t.election.startsWith("LS") ? " (LS)" : ""),
    share: t.bjp_share,
    seats: t.bjp_seats,
    seatWord: t.seats_word,
  }));

  const turnout = d.trend.rows.map((t) => ({ e: t.election, pct: t.turnout }));
  const tmax = Math.max(...turnout.map((t) => t.pct || 0), 1);

  return (
    <>
      <div className="hero">
        <div className="slogan">
          ❝ Sabka Saath Sabka Vikas
          <br />
          Sabka Vishwas Sabka Prayas<small>— Narendra Modi</small>
        </div>
        <div className="leaders">
          <img src={`${API_IMG}/assets/portraits/yogi_adityanath.png`} alt="Yogi Adityanath" />
          <img src={`${API_IMG}/assets/portraits/narendra_modi.png`} alt="Narendra Modi" />
        </div>
      </div>

      <div className="kpirow">
        <div className="kcard seats">
          <div>
            <div className="t">{isLS ? "BJP AC Leads in UP (Lok Sabha)" : "BJP Seats in UP Assembly"}</div>
            <div className="n">
              {bjpSeats} <small>/ {o.seats_counted}</small>
            </div>
            <div className="d">
              {seatPct.toFixed(1)}% {isLS ? "leads" : "seats"} ·{" "}
              {o.seats.map((s) => `${s.party} ${s.seats}`).join(" · ")}
            </div>
          </div>
          <div>
            <Gauge pct={seatPct} label={`${seatPct.toFixed(1)}%`} />
          </div>
        </div>
        <div className="kcard share">
          <div>
            <div className="t">Average Vote Share {isLS ? "(LS)" : "(VS)"}</div>
            <div className="n">{o.avg_share != null ? `${o.avg_share.toFixed(1)}%` : "—"}</div>
            <div className="d">
              {dShare != null ? `${dShare >= 0 ? "↗ +" : "↘ "}${dShare.toFixed(1)}pp` : "—"} vs {YR[vs]}
              {o.avg_share_vs != null ? ` (${o.avg_share_vs.toFixed(1)}%)` : ""}
            </div>
          </div>
          <div style={{ fontSize: 44 }}>📈</div>
        </div>
      </div>

      <Finder acs={acs} />

      <div className="panel">
        <div className="sectionhead">
          <h2>Assembly Constituency (AC) Categorisation</h2>
          <span>Total ACs: {acTotal}</span>
        </div>
        <div className="zonegrid">
          {o.ac_zones.map((z) => (
            <Link className={`zcard ${zclass(z.zone)}`} key={z.zone} href={`/zone/${encodeURIComponent(z.zone)}`}>
              <div className="zhead">
                <span className="zdot">{ZGLYPH[z.zone] || "•"}</span>
                {z.zone.toUpperCase()}
                <span className="cnt">
                  {z.acs} ACs <small>({((100 * z.acs) / (acTotal || 1)).toFixed(1)}%)</small>
                </span>
              </div>
              <div className="zperf">
                <Perf label="Best Performing" p={z.best} />
                <Perf label="Least Performing" p={z.worst} />
              </div>
            </Link>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="sectionhead">
          <h2>Booth Categorisation</h2>
          <span>Total Booths: {inr(boothTotal)}</span>
        </div>
        <div className="zonegrid">
          {o.booth_zones.map((z) => (
            <div className={`zcard ${zclass(z.zone)}`} key={z.zone}>
              <div className="zhead">
                <span className="zdot">{ZGLYPH[z.zone] || "•"}</span>
                {z.zone.toUpperCase()}
                <span className="cnt">
                  {inr(z.booths)} <small>({((100 * z.booths) / (boothTotal || 1)).toFixed(1)}%)</small>
                </span>
              </div>
              {z.top ? (
                <div className="small" style={{ marginTop: 6 }}>
                  Top Booth <b>No. {z.top.ps}</b> — {z.top.ac_name} (AC{" "}
                  <Link href={`/ac/${z.top.ac}`}>{z.top.ac}</Link>)<br />
                  <b>{pct1(z.top.share)}</b> <Delta cur={z.top.share} prev={z.top.share_vs} />
                </div>
              ) : (
                <div className="muted small">no booth data</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="duo">
        <div className="panel">
          <div className="sectionhead">
            <h2>BJP Trajectory 2017–2024</h2>
            <span>share + {isLS ? "leads" : "seats"}</span>
          </div>
          <TrendChart points={points} />
          <p className="small muted">VS years = assembly seats won; LS years = segment leads. LS2019/VS2022 use converted-booth subsets (see notes).</p>
        </div>
        <div className="panel">
          <div className="sectionhead">
            <h2>Turnout Trend</h2>
            <span>polled ÷ electors</span>
          </div>
          {turnout.map((t) => (
            <div className="relrow" key={t.e}>
              <span>{YR[t.e]}</span>
              <span className="reltrack">
                <i style={{ width: `${((t.pct || 0) / tmax) * 100}%`, background: "#2456a6" }} />
              </span>
              <b>{t.pct != null ? `${t.pct.toFixed(1)}%` : "—"}</b>
            </div>
          ))}
          <p className="small muted">From converted booth sums per election.</p>
        </div>
      </div>

      <div className="duo">
        <div className="panel">
          <div className="sectionhead">
            <h2>Average UP Voter Profile</h2>
          </div>
          <div className="votergrid">
            <Donut
              size={96}
              segs={[
                ["Male", o.voter.male_pct || 0, "#2456a6"],
                ["Female", o.voter.female_pct || 0, "#e0508a"],
              ]}
            />
            <div>
              <div className="mf" style={{ textAlign: "left" }}>
                <b>♂ {pct1(o.voter.male_pct)} · ♀ {pct1(o.voter.female_pct)}</b>
                <span>
                  Voting {pct1(o.voter.voting_pct)}
                  {o.voter.from !== election ? ` (${YR[o.voter.from]})` : ""}
                </span>
              </div>
            </div>
          </div>
        </div>
        <div className="panel">
          <div className="sectionhead">
            <h2>
              Religion-wise Population <span className="small muted">(Estimated)</span>
            </h2>
          </div>
          {RELS.map((r) => (
            <div className="relrow" key={r}>
              <span>
                <span style={{ color: RELCOLOR[r] }}>●</span> {RELABEL[r]}
              </span>
              <span className="reltrack">
                <i style={{ width: `${Math.min(100, o.religion[r] || 0)}%`, background: RELCOLOR[r] }} />
              </span>
              <b>{pct1(o.religion[r])}</b>
            </div>
          ))}
          <p className="small muted">Electors-weighted modeled means, 2017 roll.</p>
        </div>
      </div>

      {o.notes.length > 0 && <div className="panel small muted">Notes: {o.notes.join(" · ")}</div>}
    </>
  );
}

function Perf({ label, p }) {
  if (!p) return <div className="muted">—</div>;
  return (
    <div>
      <div className="pl">{label}</div>
      <div className="pn">{p.ac_name}</div>
      <div>
        <b>{pct1(p.share)}</b> <Delta cur={p.share} prev={p.share_vs} />
      </div>
    </div>
  );
}

function Finder({ acs }) {
  const [q, setQ] = useState("");
  const all = useMemo(() => {
    const seen = {};
    acs.rows.forEach((r) => {
      if (!seen[r.ac]) seen[r.ac] = [r.ac_name, r.district];
    });
    return Object.entries(seen).map(([ac, [name, dist]]) => ({ ac, name, dist }));
  }, [acs]);
  const hits = q.trim()
    ? all
        .filter((r) => `${r.name} ${r.dist} ${r.ac}`.toLowerCase().includes(q.trim().toLowerCase()))
        .slice(0, 8)
    : [];
  const dists = useMemo(() => {
    const m = {};
    all.forEach((r) => {
      (m[r.dist] = m[r.dist] || []).push(r);
    });
    return Object.keys(m).sort();
  }, [all]);
  return (
    <div className="panel">
      <div className="sectionhead">
        <h2>Find a Constituency</h2>
        <span>{all.length} ACs · {dists.length} districts</span>
      </div>
      <input
        className="searchbar"
        type="search"
        placeholder="Type AC name, district or number… (e.g. Amethi, Agra, 88)"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {hits.length > 0 && (
        <div className="cols" style={{ marginBottom: 8 }}>
          {hits.map((r) => (
            <Link key={r.ac} href={`/ac/${r.ac}`} className="pill">
              {r.name} ({r.ac})
            </Link>
          ))}
        </div>
      )}
      <details>
        <summary className="small" style={{ cursor: "pointer", fontWeight: 700 }}>
          Browse by district ({dists.length})
        </summary>
        <div style={{ columns: "3 220px", marginTop: 8 }}>
          {dists.map((d) => (
            <details key={d} style={{ breakInside: "avoid", marginBottom: 6 }}>
              <summary className="small" style={{ cursor: "pointer" }}>
                {d}
              </summary>
              <div className="small">
                {all
                  .filter((r) => r.dist === d)
                  .map((r) => (
                    <div key={r.ac}>
                      <Link href={`/ac/${r.ac}`}>
                        {r.name} ({r.ac})
                      </Link>
                    </div>
                  ))}
              </div>
            </details>
          ))}
        </div>
      </details>
    </div>
  );
}
