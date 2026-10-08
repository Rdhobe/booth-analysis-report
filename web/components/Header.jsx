"use client";

import Link from "next/link";
import { API_IMG } from "@/lib/upbi";

export default function Header({ election, vs, onElection, onVs }) {
  return (
    <header>
      <div className="wrap head">
        <div className="brand">
          <img className="logo" src={`${API_IMG}/assets/parties/Logo_of_the_Bharatiya_Janata_Party.svg`} alt="lotus" />
          <div>
            <div className="greet">
              नमस्कार <span>Rohit Ji</span> ! 🙏
            </div>
            <p className="tsub">Uttar Pradesh Elections Dashboard</p>
          </div>
        </div>
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
        <div className="leaders">
          <img src={`${API_IMG}/assets/portraits/narendra_modi.png`} alt="Narendra Modi" title="Narendra Modi" />
          <img src={`${API_IMG}/assets/portraits/yogi_adityanath.png`} alt="Yogi Adityanath" title="Yogi Adityanath" />
        </div>
      </div>
      <div className="wrap">
        <nav className="mainnav">
          <Link href="/">Dashboard</Link>
        </nav>
      </div>
    </header>
  );
}
