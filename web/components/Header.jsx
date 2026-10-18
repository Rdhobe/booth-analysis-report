"use client";

import Link from "next/link";

// Neutral header: the product name in plain text only. No party, leader or organisation logos or images anywhere in the UI.
export default function Header({ election, vs, onElection, onVs, hideSelectors = false }) {
  return (
    <header>
      <div className="wrap head">
        <div className="brand">
          <div>
            <div className="greet">UP Booth Intelligence</div>
            <p className="tsub">Uttar Pradesh election results explorer</p>
          </div>
        </div>
        {hideSelectors ? null : (
          <div className="selrow">
            <select value="UP" disabled>
              <option value="UP">Uttar Pradesh</option>
            </select>
            <select value={election} onChange={(e) => onElection(e.target.value)}>
              <option value="LS2024">2024 (Current)</option>
              <option value="VS2022">2022</option>
              <option value="LS2019">2019</option>
              <option value="VS2017">2017</option>
            </select>
            <select value={vs} onChange={(e) => onVs(e.target.value)}>
              <option value="VS2022">vs 2022</option>
              <option value="VS2017">vs 2017</option>
              <option value="LS2019">vs 2019</option>
              <option value="LS2024">vs 2024</option>
            </select>
          </div>
        )}
      </div>
      <div className="wrap">
        <nav className="mainnav">
          <Link href="/insights">Insights (all parties)</Link>
          <Link href="/booths">Booth dashboard</Link>
        </nav>
      </div>
    </header>
  );
}
