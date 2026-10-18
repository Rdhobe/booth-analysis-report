// Shared client helpers. Data always flows through Next.js /api/*
// route handlers (key stays server-side). The UI shows no logos or images.

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

export const inr = (v) =>
  v == null ? "—" : Number(v).toLocaleString("en-IN");
export const pct1 = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
export const zclass = (z) => `z-${String(z || "").split(" ")[0]}`;

