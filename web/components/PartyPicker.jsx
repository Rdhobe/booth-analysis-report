"use client";

// Equal-weight party picker for the booth pages. Every party is the same button; none is preselected.

const alpha = (list) => [...list].sort();

export function PartySwitch({ parties, party, onParty }) {
  if (!parties || parties.length < 2) return null;
  return (
    <div className="partysel" role="group" aria-label="View booth analysis as party">
      <span className="small muted">View as</span>
      {alpha(parties).map((p) => (
        <button key={p} type="button" aria-pressed={p === party} className={p === party ? "on" : ""} onClick={() => onParty(p)}>
          {p}
        </button>
      ))}
    </div>
  );
}

export function PartyChooser({ parties, onParty, what = "the booth analysis" }) {
  return (
    <div className="panel partychooser">
      <h2>Choose a party</h2>
      <p>
        The booth pages show {what} from <b>one party&apos;s side</b>: its share in each booth against its strongest opponent in that seat, and the
        zone that follows. Pick the party to look from; you can switch at any time and the same booths are shown from the other side.
      </p>
      <div className="partysel big" role="group" aria-label="Choose a party">
        {alpha(parties).map((p) => (
          <button key={p} type="button" aria-pressed="false" onClick={() => onParty(p)}>
            {p}
          </button>
        ))}
      </div>
      <p className="small muted">
        Parties are listed alphabetically; none is the default. A party is only compared in the seats and elections
        where it stood. For all parties side by side, use the Insights pages.
      </p>
    </div>
  );
}
