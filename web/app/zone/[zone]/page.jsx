"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Header from "@/components/Header";
import { YR, get, pct1 } from "@/lib/upbi";

export default function ZonePage({ params, searchParams }) {
  const zone = decodeURIComponent(params.zone);
  const [election, setElection] = useState(searchParams.e || "LS2024");
  const [vs, setVs] = useState(searchParams.vs || "VS2022");
  const [o, setO] = useState(null);
  const [info, setInfo] = useState(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    setO(null);
    setErr("");
    Promise.all([
      get(`overview?election=${election}&vs=${vs}`),
      get("acs"),
    ])
      .then(([ov, acs]) => {
        setO(ov);
        setInfo(acs);
      })
      .catch((e) => setErr(e.message));
  }, [election, vs]);

  const rows = useMemo(() => {
    if (!o || !info) return [];
    const z = o.ac_zones.find((x) => x.zone === zone);
    if (!z) return [];
    const names = {};
    info.rows.forEach((r) => {
      if (!(r.ac in names)) names[r.ac] = [r.ac_name, r.district];
    });
    return z.members.map((ac) => {
      const s = o.ac_shares[String(ac)] || [null, null];
      const nm = names[ac] || ["", ""];
      return {
        ac,
        name: nm[0],
        dist: nm[1],
        cur: s[0],
        prev: s[1],
        ch: s[0] != null && s[1] != null ? s[0] - s[1] : null,
      };
    });
  }, [o, info, zone]);

  const list = rows
    .filter((r) =>
      `${r.name} ${r.dist} ${r.ac}`.toLowerCase().includes(q.toLowerCase())
    )
    .sort((a, b) => (b.ch ?? -1e9) - (a.ch ?? -1e9));

  return (
    <>
      <Header election={election} vs={vs} onElection={setElection} onVs={setVs} />
      <main className="wrap">
        {err ? (
          <div className="panel err">API unreachable: {err}</div>
        ) : !o ? (
          <div className="skel" />
        ) : (
          <div className="panel">
            <h2>
              <Link href="/" className="backbtn" title="back to dashboard">
                ←
              </Link>{" "}
              {zone} ACs ({rows.length})
            </h2>
            <input
              className="searchbar"
              type="search"
              placeholder="Search Assembly Constituency…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <div style={{ overflowX: "auto" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>AC Name</th>
                    <th>District</th>
                    <th>BJP {YR[election]}</th>
                    <th>BJP {YR[vs]}</th>
                    <th>Change</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((r, i) => (
                    <tr key={r.ac}>
                      <td>{i + 1}</td>
                      <td>
                        <Link href={`/ac/${r.ac}`}>
                          {r.name} ({r.ac})
                        </Link>
                      </td>
                      <td>{r.dist}</td>
                      <td>{pct1(r.cur)}</td>
                      <td>{pct1(r.prev)}</td>
                      <td>
                        {r.ch == null ? (
                          <span className="muted">—</span>
                        ) : (
                          <b style={{ color: r.ch >= 0 ? "var(--grn)" : "var(--red)" }}>
                            {r.ch >= 0 ? "▲" : "▼"} {Math.abs(r.ch).toFixed(1)}pp
                          </b>
                        )}
                      </td>
                      <td>
                        <Link href={`/ac/${r.ac}`}>›</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
