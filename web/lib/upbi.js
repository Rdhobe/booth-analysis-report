// Shared client helpers. Data always flows through Next.js /api/*
// route handlers (key stays server-side). The UI shows no logos or images.

import { useCallback, useEffect, useState } from "react";

// The booth pages are seen from one party's side. The choice lives in the URL (?party=SP) so a link keeps it.
// There is no hidden default in the UI: until a party is picked, `party` is null and the pages ask.
export function useParty() {
  const [party, setPartyState] = useState(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search).get("party");
      if (p) setPartyState(p.toUpperCase());
    } catch (e) {
      /* no URL access: the page asks for a party */
    }
    setReady(true);
  }, []);
  const setParty = useCallback((p) => {
    setPartyState(p || null);
    try {
      const u = new URL(window.location.href);
      if (p) u.searchParams.set("party", p);
      else u.searchParams.delete("party");
      window.history.replaceState(null, "", u);
    } catch (e) {
      /* the choice still works for this page view */
    }
  }, []);
  return [party, setParty, ready];
}

// the API refuses a party it does not know (400 "party must be one of ..."); the pages then fall back to the chooser
export const isBadParty = (e) => /party must be one of/.test(String((e && e.message) || ""));

// what to tell the user when a booth page cannot load
export const loadError = (msg) =>
  /store not found/.test(String(msg))
    ? "The booth database is not available on this server. It is built from the raw booth sheets (see server/README.md, \"Booth store\"); the Insights pages do not need it."
    : `API unreachable: ${msg} (is the FastAPI server running? See web/README.)`;

// keep the chosen party when following a link inside the booth pages
export const withParty = (href, party) => (party ? `${href}${href.includes("?") ? "&" : "?"}party=${encodeURIComponent(party)}` : href);

export const ELECTIONS = ["VS2017", "LS2019", "VS2022", "LS2024"];
export const YR = { VS2017: "2017", LS2019: "2019", VS2022: "2022", LS2024: "2024" };
export const ZONES = ["Safe", "Favorable", "Battlefield", "Difficult", "Data Not sufficient"];
export const ZGLYPH = { Safe: "✓", Favorable: "↗", Battlefield: "◎", Difficult: "!", "Data Not sufficient": "?" };
export const RELS = ["hindu", "muslim", "christian", "sikh", "jain", "buddhist", "parsi", "others"];
export const RELABEL = { hindu: "Hindu", muslim: "Muslim", christian: "Christian", sikh: "Sikh", jain: "Jain", buddhist: "Buddhist", parsi: "Parsi", others: "Others" };

const _flight = new Map();

export async function get(path) {
  // Deduplicate in-flight + repeat reads (tab switches remount and
  // would otherwise refetch). Responses are immutable until rebuild.
  if (!_flight.has(path)) {
    _flight.set(
      path,
      (async () => {
        const r = await fetch(`/api/${path}`, { cache: "no-store" });
        if (!r.ok) {
          const t = (await r.text()).slice(0, 300);
          _flight.delete(path);
          throw new Error(`${path} -> ${r.status} ${t}`);
        }
        return r.json();
      })()
    );
  }
  return _flight.get(path);
}

export async function post(path, body) {
  const r = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!r.ok) {
    const t = (await r.text()).slice(0, 300);
    throw new Error(`${path} -> ${r.status} ${t}`);
  }
  return r.json();
}

export const inr = (v) =>
  v == null ? "—" : Number(v).toLocaleString("en-IN");
export const pct1 = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
export const zclass = (z) => `z-${String(z || "").split(" ")[0]}`;

