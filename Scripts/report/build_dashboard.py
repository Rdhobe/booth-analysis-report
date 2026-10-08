"""Dashboard bundle + single-file HTML dashboard.

Reads output/booth_data.db and writes:
- output/dashboard_data.json (compact aggregates + Agra booth detail)
- output/dashboard.html (self-contained: data inlined, no CDN, no server;
  open directly in a browser)

Contents: KPIs, schematic district tile-grid map (not to scale),
party trends, Agra booth explorer (winner/share/margin/turnout/BJP),
methods & caveats.

Usage: python Scripts/build_dashboard.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "output" / "booth_data.db"
BUNDLE = ROOT / "output" / "dashboard_data.json"
HTML = ROOT / "output" / "dashboard.html"

PARTY_COLORS = {"BJP": "#f5821f", "SP": "#e31e24", "BSP": "#22409a",
                "INC": "#00a651", "IND": "#888888", "NOTA": "#bbbbbb"}

GRID_POS = {
 "Saharanpur": (0, 0), "Shamli": (1, 0), "Muzaffarnagar": (2, 0), "Bijnor": (3, 0),
 "Moradabad": (4, 0), "Rampur": (5, 0), "Bareilly": (6, 0), "Pilibhit": (7, 0),
 "Shahjahanpur": (8, 0), "Lakhimpur Kheri": (9, 0), "Bahraich": (10, 0),
 "Shrawasti": (11, 0), "Balrampur": (12, 0), "Siddharthnagar": (13, 0),
 "Baghpat": (0, 1), "Meerut": (1, 1), "Amroha": (2, 1), "Sambhal": (3, 1),
 "Budaun": (4, 1), "Kasganj": (5, 1), "Farrukhabad": (6, 1), "Mainpuri": (7, 1),
 "Kannauj": (8, 1), "Hardoi": (9, 1), "Sitapur": (10, 1), "Gonda": (11, 1),
 "Ayodhya": (12, 1), "Ambedkar Nagar": (13, 1),
 "Ghaziabad": (0, 2), "Hapur": (1, 2), "Bulandshahr": (2, 2), "Aligarh": (3, 2),
 "Hathras": (4, 2), "Etah": (5, 2), "Etawah": (6, 2), "Auraiya": (7, 2),
 "Kanpur Dehat": (8, 2), "Unnao": (9, 2), "Lucknow": (10, 2), "Barabanki": (11, 2),
 "Jaunpur": (12, 2), "Azamgarh": (13, 2),
 "Gautam Buddha Nagar": (0, 3), "Mathura": (1, 3), "Agra": (2, 3),
 "Firozabad": (3, 3), "Kanpur Nagar": (5, 3), "Raebareli": (6, 3),
 "Fatehpur": (7, 3), "Kaushambi": (8, 3), "Prayagraj": (9, 3),
 "Bhadohi": (10, 3), "Varanasi": (11, 3), "Ghazipur": (12, 3), "Ballia": (13, 3),
 "Jalaun": (0, 4), "Jhansi": (1, 4), "Lalitpur": (2, 4), "Hamirpur": (3, 4),
 "Mahoba": (4, 4), "Banda": (5, 4), "Chitrakoot": (6, 4), "Mirzapur": (7, 4),
 "Sonbhadra": (8, 4), "Chandauli": (9, 4), "Mau": (10, 4), "Deoria": (11, 4),
 "Kushinagar": (12, 4), "Gorakhpur": (13, 4),
 "Sultanpur": (5, 5), "Amethi": (6, 5), "Pratapgarh": (7, 5), "Basti": (8, 5),
 "Sant Kabir Nagar": (9, 5), "Maharajganj": (10, 5),
}
GRID_ALIAS = {"Allahabad": "Prayagraj", "Pryagraj": "Prayagraj",
              "Faizabad": "Ayodhya", "Bheem Nagar": "Sambhal",
              "Panchsheel Nagar": "Hapur", "Prabuddha Nagar": "Shamli",
              "Mahamayanagar": "Hathras", "Kanshiramnagar": "Kasganj",
              "Jyoti Ba Phole Nagar": "Amroha",
              "Sant Ravidas Nagar": "Bhadohi", "CSJM Nagar": "Amethi",
              "Sant Kabirnagar": "Sant Kabir Nagar", "Shravasti": "Shrawasti",
              "Baharaich": "Bahraich", "Manpuri": "Mainpuri",
              "Bulandsahar": "Bulandshahr", "Kheri": "Lakhimpur Kheri",
              "Badaun": "Budaun"}


def grid_for(districts):
    used, out, over = set(), [], []
    for d in sorted(districts):
        pos = GRID_POS.get(GRID_ALIAS.get(d, d))
        if pos and pos not in used:
            used.add(pos)
            out.append({"n": d, "x": pos[0], "y": pos[1]})
        else:
            over.append(d)
    for i, d in enumerate(over):
        out.append({"n": d, "x": i % 14, "y": 6 + i // 14})
    return out


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>UP Booth Intelligence — Dashboard</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#222}
header{background:#1F4E79;color:#fff;padding:14px 22px}
header h1{margin:0;font-size:22px}header p{margin:4px 0 0;font-size:13px;color:#cfe0f1}
nav{display:flex;gap:8px;padding:10px 22px;background:#fff;border-bottom:1px solid #ddd}
nav button{border:1px solid #1F4E79;background:#fff;color:#1F4E79;padding:7px 16px;border-radius:6px;cursor:pointer;font-size:14px}
nav button.on{background:#1F4E79;color:#fff}
section{padding:16px 22px;display:none}section.on{display:block}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:12px 18px;min-width:150px}
.card b{font-size:24px;display:block}.card span{font-size:12px;color:#666}
.panel{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:14px 18px;margin-bottom:16px}
.panel h3{margin:0 0 10px;font-size:16px}
.grid{display:grid;grid-template-columns:repeat(14,1fr);gap:4px}
.tile{border-radius:5px;padding:8px 2px;text-align:center;font-size:10px;cursor:pointer;color:#fff;min-height:44px;display:flex;align-items:center;justify-content:center}
.tile:hover{outline:2px solid #1F4E79}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #ddd;padding:5px 8px;text-align:left}
th{background:#1F4E79;color:#fff}
tr:nth-child(even){background:#f7f9fb}
select,input{padding:6px 10px;font-size:14px;margin-right:8px}
.note{font-size:12px;color:#666}.warn{font-size:12px;color:#9C6500}
.bar-row{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:13px}
.bar-lbl{width:150px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-wrap{flex:1;background:#eee;border-radius:4px}.bar{height:18px;border-radius:4px;color:#fff;font-size:11px;line-height:18px;padding-left:6px;white-space:nowrap}
</style>
</head>
<body>
<header><h1>UP Booth Intelligence — Analytics Dashboard</h1>
<p id="covline"></p></header>
<nav>
<button data-t="overview" class="on">Overview</button>
<button data-t="map">Map</button>
<button data-t="explore">Explore</button>
<button data-t="methods">Methods</button>
</nav>
<section id="overview" class="on">
<div class="cards" id="kpis"></div>
<div class="panel"><h3 id="topTitle"></h3><div id="covWarn"></div><div id="topParties"></div></div>
<div class="panel"><h3>Turnout % by election (electors available)</h3><div id="turnout"></div></div>
</section>
<section id="map">
<div class="panel"><h3>District map (schematic grid — not to scale)</h3>
<label>Election <select id="mapE"></select></label>
<label>Metric <select id="mapM"><option value="bjp">BJP share %</option><option value="turnout">Turnout %</option><option value="booths">Booths</option></select></label>
<span class="note" id="mapNote"></span>
<div class="grid" id="tiles" style="margin-top:10px"></div></div>
</section>
<section id="explore">
<div class="panel"><h3>District / booth explorer <span class="note">(booth detail: Agra pilot)</span></h3>
<label>District <select id="exD"></select></label>
<label>AC <select id="exA"></select></label>
<input id="exQ" placeholder="search booth / winner…" style="width:220px">
<div id="exInfo" style="margin:8px 0"></div>
<table><thead><tr><th>Booth</th><th>PS</th><th>Name</th><th>Election</th><th>Polled</th><th>Winner</th><th>Share%</th><th>Margin</th><th>Turnout%</th><th>BJP%</th></tr></thead>
<tbody id="exBody"></tbody></table>
<p class="note" id="exCount"></p></div>
</section>
<section id="methods">
<div class="panel"><h3>Methods &amp; caveats</h3>
<ul>
<li>Shares = votes / polled. Swings in percentage points on crosswalk links.</li>
<li>2017/2022 are Vidhan Sabha, 2019/2024 Lok Sabha — different electorates; cross-type swings are shown but not directly comparable.</li>
<li>2024 has no electors in Form 20: turnout N/A for 2024.</li>
<li>UNMAPPED = candidate without verified party label (excluded from party math).</li>
<li>Legacy-font booth names kept raw and flagged, never rewritten.</li>
<li>Anomaly outputs are <b>statistical outliers</b>, never fraud claims.</li>
<li>Map is a schematic tile cartogram, not geography. Coverage is partial — see convert_report.md.</li>
</ul></div>
</section>
<script>
const DATA = /*__DATA__*/null;
const PCOL = {"BJP":"#f5821f","SP":"#e31e24","BSP":"#22409a","INC":"#00a651","IND":"#888888","NOTA":"#bbbbbb"};
function pcol(p){if(PCOL[p])return PCOL[p];let h=0;for(const c of p)h=(h*31+c.charCodeAt(0))%360;return "hsl("+h+",55%,45%)";}
function fmt(n){return n==null||n===""?"—":Number(n).toLocaleString("en-IN");}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button").forEach(x=>x.classList.remove("on"));document.querySelectorAll("section").forEach(x=>x.classList.remove("on"));b.classList.add("on");document.getElementById(b.dataset.t).classList.add("on");});
// overview
(function(){
const m=DATA.meta;
document.getElementById("covline").textContent=m.booths.toLocaleString("en-IN")+" booths · "+Object.keys(DATA.districts).length+" districts · "+m.elections.join(" / ")+" · "+m.note;
const kpis=[["Booths",m.booths],["Districts",Object.keys(DATA.districts).length],["Elections",m.elections.length],["Vote rows",m.votes]];
document.getElementById("kpis").innerHTML=kpis.map(k=>'<div class="card"><b>'+fmt(k[1])+'</b><span>'+k[0]+'</span></div>').join("");
const le=m.elections[m.elections.length-1];
document.getElementById("topTitle").textContent="Top parties — "+le+" (vote % share)";
const tr=DATA.trends[le];
if(tr.mapped_pct<90)document.getElementById("covWarn").innerHTML="<p class='warn'>Only "+tr.mapped_pct+"% of polled votes carry verified party labels here (rest UNMAPPED) — shares understate true party strength.</p>";
const tp=tr.parties.slice(0,8), mx=Math.max.apply(null,tp.map(x=>x[2]).concat([1]));
document.getElementById("topParties").innerHTML=tp.map(x=>'<div class="bar-row"><div class="bar-lbl">'+x[0]+'</div><div class="bar-wrap"><div class="bar" style="width:'+(x[2]/mx*100).toFixed(1)+'%;background:'+pcol(x[0])+'">'+x[2]+'% · '+fmt(x[1])+'</div></div></div>').join("");
let th="";
m.elections.forEach(e=>{let s=0,n=0;for(const d in DATA.districts){const dd=DATA.districts[d][e];if(dd&&dd.turnout!=null){s+=dd.turnout*dd.booths;n+=dd.booths;}}const t=n? (s/n).toFixed(1)+"%":"—";th+='<div class="bar-row"><div class="bar-lbl">'+e+'</div><div class="bar-wrap"><div class="bar" style="width:'+(n?s/n:0)+'%;background:#1F4E79">'+t+'</div></div></div>';});
document.getElementById("turnout").innerHTML=th;
})();
// map
function shade(hex,frac){const n=parseInt(hex.slice(1),16),r=n>>16&255,g=n>>8&255,b=n&255,f=Math.min(1,Math.max(0,frac));const m=v=>Math.round(235+(v-235)*f);return "rgb("+m(r)+","+m(g)+","+m(b)+")";}
function drawMap(){
const e=document.getElementById("mapE").value, m=document.getElementById("mapM").value;
const box=document.getElementById("tiles");box.innerHTML="";
const cells={};DATA.grid.forEach(g=>{cells[g.y+"_"+g.x]=g.n;});
let ys=DATA.grid.map(g=>g.y), ye=Math.max.apply(null,ys.concat([0]));
for(let y=0;y<=ye;y++){for(let x=0;x<14;x++){
const t=document.createElement("div");
const name=cells[y+"_"+x];
if(!name){t.style.visibility="hidden";box.appendChild(t);continue;}
const dd=(DATA.districts[name]||{})[e];
let val=null,txt=name+(dd?" · "+e:" (no data)");
if(dd){if(m==="bjp"){const bp=(dd.parties.find(p=>p[0]==="BJP")||[0,0]);val=bp[1]/dd.polled*100;txt+=" · BJP "+val.toFixed(1)+"%";}else if(m==="turnout"){val=dd.turnout;txt+=" · Turnout "+(val==null?"—":val+"%");}else{val=dd.booths;txt+=" · "+val+" booths";}}
t.className="tile";t.title=txt;
t.textContent=name.length>12?name.slice(0,11)+"…":name;
let bg="#ccc";
if(val!=null){if(m==="booths"){const mx=800;bg=shade("#1F4E79",Math.min(1,val/mx));}else{const cols=m==="bjp"?["#fde8d0","#f5821f"]:["#dbe9f6","#1F4E79"];const f=Math.min(1,val/60);bg="color-mix(in srgb,"+cols[1]+" "+Math.round(f*100)+"%,"+cols[0]+")";}}
t.style.background=bg;t.style.color=(m!=="booths"&&val!=null&&val>35)?"#fff":"#222";
t.onclick=()=>{goExplore(name);};
box.appendChild(t);}}
document.getElementById("mapNote").textContent="election "+e+" · click a tile to explore";
}
(function(){
const se=document.getElementById("mapE");
DATA.meta.elections.forEach(e=>{const o=document.createElement("option");o.value=e;o.textContent=e;se.appendChild(o);});
se.value=DATA.meta.elections[DATA.meta.elections.length-1];
document.getElementById("mapM").onchange=drawMap;se.onchange=drawMap;drawMap();
})();
// explore
function goExplore(d){document.querySelectorAll("nav button").forEach(x=>x.classList.remove("on"));document.querySelectorAll("section").forEach(x=>x.classList.remove("on"));document.querySelector('button[data-t="explore"]').classList.add("on");document.getElementById("explore").classList.add("on");document.getElementById("exD").value=d;fillAC();drawEx();}
(function(){
const sd=document.getElementById("exD");
Object.keys(DATA.districts).sort().forEach(d=>{const o=document.createElement("option");o.value=d;o.textContent=d;sd.appendChild(o);});
sd.value="Agra";sd.onchange=()=>{fillAC();drawEx();};
document.getElementById("exA").onchange=drawEx;document.getElementById("exQ").oninput=drawEx;
fillAC();drawEx();
})();
function fillAC(){
const d=document.getElementById("exD").value;
const acs=[...new Set(DATA.agra.filter(r=>distOf(r)===d).map(r=>r.ac))].sort((a,b)=>a-b);
const sa=document.getElementById("exA");sa.innerHTML="";
acs.forEach(a=>{const o=document.createElement("option");o.value=a;o.textContent="AC "+a;sa.appendChild(o);});
if(!acs.length)sa.innerHTML="<option value=''>—</option>";
}
function distOf(r){return "Agra";}
function drawEx(){
const d=document.getElementById("exD").value, ac=document.getElementById("exA").value;
const q=(document.getElementById("exQ").value||"").toLowerCase();
const dd=DATA.districts[d];let html="";
if(dd){const es=Object.keys(dd);html="Elections: "+es.join(", ")+" · Booths: "+es.map(e=>dd[e].booths).join("+")+" · Latest "+es[es.length-1]+": "+dd[es[es.length-1]].parties.slice(0,4).map(p=>p[0]+" "+((p[1]/dd[es[es.length-1]].polled)*100).toFixed(1)+"%").join(", ");}
document.getElementById("exInfo").innerHTML=html+(d!=="Agra"?" <span class='warn'>Booth detail shown for the Agra pilot only.</span>":"");
let rows=DATA.agra.filter(r=>String(r.ac)===String(ac));
if(q)rows=rows.filter(r=>(r.u+" "+(r.n||"")+" "+(r.w||"")).toLowerCase().includes(q));
rows=rows.slice().sort((a,b)=>a.ps-b.ps).slice(0,300);
document.getElementById("exBody").innerHTML=rows.map(r=>"<tr><td>"+r.u+"</td><td>"+r.ps+"</td><td>"+(r.n||"")+"</td><td>"+r.e+"</td><td>"+fmt(r.p)+"</td><td>"+r.w+"</td><td>"+r.ws+"</td><td>"+r.m+"</td><td>"+(r.t==null?"—":r.t)+"</td><td>"+r.bjp+"</td></tr>").join("");
document.getElementById("exCount").textContent=rows.length+" rows shown (AC "+ac+")";
}
</script>
</body>
</html>
"""


def build_bundle(cx):
    """Compact aggregates + Agra booth detail (same as dashboard_data.json)."""
    booths = cx.execute("SELECT COUNT(*) FROM booth").fetchone()[0]
    votes = cx.execute("SELECT COUNT(*) FROM vote").fetchone()[0]
    files = cx.execute("SELECT COUNT(*) FROM file_coverage").fetchone()[0]
    elections = [r[0] for r in cx.execute(
        "SELECT DISTINCT election FROM booth ORDER BY election")]
    districts, trends, agra = {}, {}, []
    for (d,) in cx.execute("SELECT DISTINCT district FROM booth"):
        dd = {}
        for e in elections:
            row = cx.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(polled),0) polled, "
                "COALESCE(SUM(electors),0) electors FROM booth "
                "WHERE district=? AND election=?", (d, e)).fetchone()
            if not row[0]:
                continue
            pv = cx.execute(
                "SELECT party, SUM(votes) v FROM vote JOIN booth USING(booth_uid) "
                "WHERE district=? AND election=? AND party NOT IN ('NOTA','UNMAPPED') "
                "GROUP BY party ORDER BY v DESC", (d, e)).fetchall()
            pv = [(r[0], r[1]) for r in pv]
            top, rest = pv[:6], sum(v for _, v in pv[6:])
            dd[e] = {"booths": row[0], "polled": row[1],
                     "turnout": round(row[1] / row[2] * 100, 1) if row[2] else None,
                     "parties": [[p, v] for p, v in top] + ([["OTHER", rest]] if rest else []),
                     "valid_check": None}
        if dd:
            districts[d] = dd
    for e in elections:
        pv = cx.execute(
            "SELECT party, SUM(votes) v FROM vote JOIN booth USING(booth_uid) "
            "WHERE election=? AND party NOT IN ('NOTA','UNMAPPED') "
            "GROUP BY party ORDER BY v DESC LIMIT 8", (e,)).fetchall()
        tot = cx.execute("SELECT COALESCE(SUM(polled),0) FROM booth WHERE election=?",
                         (e,)).fetchone()[0] or 1
        mapped = sum(v for _, v in pv)
        trends[e] = {"polled": tot,
                     "mapped_pct": round(mapped / tot * 100, 1),
                     "parties": [[p, v, round(v / tot * 100, 2)] for p, v in pv]}
    for b in cx.execute(
            "SELECT booth_uid, election, ac_no, ps_no, ps_name, polled, "
            "electors FROM booth WHERE district='Agra'"):
        uid = b[0]
        pv = cx.execute(
            "SELECT party, SUM(votes) v FROM vote WHERE booth_uid=? "
            "AND party NOT IN ('NOTA','UNMAPPED') GROUP BY party "
            "ORDER BY v DESC LIMIT 3", (uid,)).fetchall()
        pv = [(r[0], r[1]) for r in pv]
        if not pv:
            continue
        polled = b[5] or sum(v for _, v in pv) or 1
        w, wv = pv[0][0], pv[0][1]
        runner = sorted([v for _, v in pv], reverse=True)
        runner = runner[1] if len(runner) > 1 else 0
        agra.append({"u": uid, "e": b[1], "ac": b[2], "ps": b[3], "n": b[4],
                     "p": polled, "w": w, "ws": round(wv / polled * 100, 1),
                     "m": round((wv - runner) / polled * 100, 1),
                     "t": round(polled / b[6] * 100, 1) if b[6] else None,
                     "bjp": round(dict(pv).get("BJP", 0) / polled * 100, 1)})
    return {"meta": {"booths": booths, "votes": votes, "files": files,
                     "elections": elections,
                     "note": "2024 has no electors (turnout N/A). Shares of polled. "
                             "Coverage partial: see convert_report.md."},
            "districts": districts, "trends": trends, "agra": agra}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Bundle + single-file dashboard")
    ap.add_argument("--db", default="output/booth_data.db")
    args = ap.parse_args(argv)
    t0 = time.time()
    cx = sqlite3.connect(str(ROOT / args.db))
    bundle = build_bundle(cx)
    cx.close()
    bundle["grid"] = grid_for(sorted(bundle["districts"]))
    bundle["meta"]["grid_note"] = "schematic tile cartogram, not to scale"
    need = {"meta", "districts", "trends", "agra", "grid"}
    assert not (need - set(bundle)), need - set(bundle)
    (ROOT / "output" / "dashboard_data.json").write_text(
        json.dumps(bundle, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    html = HTML_TEMPLATE.replace("/*__DATA__*/null",
                                 json.dumps(bundle, ensure_ascii=False,
                                            separators=(",", ":")))
    (ROOT / "output" / "dashboard.html").write_text(html, encoding="utf-8")
    import os
    print("bundle + dashboard in %.0fs; html %d KB" % (
        time.time() - t0,
        os.path.getsize(ROOT / "output" / "dashboard.html") // 1024), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
