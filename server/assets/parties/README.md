# parties — party logos

Served at `/assets/parties/<file>`. PNG with transparency, square,
~256px. One file per party code, lowercase:

- `bjp.png`, `sp.png`, `bsp.png`, `inc.png`, `aap.png`, `rlm.png` …
- `ind.png` (independents, generic)
- `nota.png` (NOTA, generic)
- `other.png` (fallback for any code without a file)

Frontend looks up `/assets/parties/&lt;party.toLowerCase()&gt;.png`
and falls back to `other.png`.
