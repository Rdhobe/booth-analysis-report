# SECURITY.md: Privacy, Legal, Ethics, Threat Model

> This is engineering guidance, not legal advice. Get counsel's review before any public release or use with live voters.

## 1. Why this project is sensitive
It combines voter-roll data, community-level inference, and political sentiment. Caste and political opinion are among the most sensitive categories of personal data in India, and group-level misuse (targeting, suppression, harassment) is a real harm.

## 2. Data classification
| Class | Examples | Handling |
|---|---|---|
| **Restricted** | Raw roll PDFs, parsed name-level tables, API tokens | Encrypted at rest, access-logged, **deleted after aggregation**, never in git |
| **Confidential** | Booth-level modeled composition, anomaly flags, raw social text | Role-based access, TTL for raw text (30 days) |
| **Internal** | Aggregated sentiment, swing tables | Authenticated access |
| **Public (if approved)** | AC-level historical results | Publishable |

## 3. Privacy controls
- **Data minimization:** drop names/EPIC numbers immediately after producing counts. Do not persist EPIC, house numbers, photos, or relative names.
- **Aggregation threshold:** no composition output for booths with < 200 electors; apply k-anonymity style suppression (cells < 10 masked).
- **No individual linkage:** never join social-media identities to roll rows. Store no usernames or handles; hash text, truncate TTL.
- **Differential-style noise** (optional) on any exported small-cell counts.
- **Purpose limitation:** analytics only. No micro-targeting of messages to people by inferred caste, and no tool exports that list individuals.
- **DPDP Act 2023 (India):** assess lawful basis, notice, and exemptions for the data you hold; roll data being publicly accessible does not automatically permit any processing. Seek legal advice.

## 4. Election-law compliance
- Observe statutory restrictions on publishing opinion/exit-poll type content around polling (RP Act 1951, ss. 126 and 126A) and **ECI/MCC guidance**. Compliance Mode (DESIGN.md §6) must be wired to the official schedule.
- Do not use outputs to influence voters unlawfully, to publish unverified allegations, or to identify voters' choices at booth level in a way that endangers ballot secrecy. Small booths with lopsided results can effectively reveal community voting; consider minimum-size suppression for public views.

## 5. Platform & scraping
- Official APIs only; honor ToS, rate limits, and takedown requests.
- No collection of private/closed groups or logged-in-only content.
- Document every source in `SOURCES_LOG.csv`.

## 6. Application security
- Auth on the dashboard (OIDC/SSO); RBAC: `viewer`, `analyst`, `admin`.
- HTTPS everywhere; HSTS; secure cookies.
- Secrets in env/secret manager; rotate API keys; `.env` git-ignored; `detect-secrets` pre-commit.
- Dependency hygiene: pinned versions, `pip-audit`/Dependabot, Docker image scan.
- Input handling: never `eval`; sanitize any user-entered filters; restrict file uploads (PDF only, size cap, sandboxed parsing, since PDFs can be hostile).
- Logging: audit log for exports and admin actions; no PII in logs.
- Backups: encrypted; test restores.

## 7. Threat model (STRIDE-lite)
| Threat | Example | Mitigation |
|---|---|---|
| Spoofing | Unauthorized dashboard access | SSO, MFA for admins |
| Tampering | Poisoned sentiment feed (bot floods) | Dedupe, burst detection, per-source caps, anomaly alerts on feed volume |
| Repudiation | Unlogged exports | Audit logs |
| Information disclosure | Leak of booth composition / raw rolls | Aggregation-only storage, RBAC, encryption, watermark exports |
| DoS | Heavy queries on the map | Caching, rate limits, pre-aggregation |
| Elevation | Malicious PDF exploiting parser | Sandboxed worker, updated libs |
| Misuse | Community targeting, harassment | Purpose limitation, suppression thresholds, access review, ethics sign-off |

## 8. Ethics checklist (before each release)
- [ ] Outputs labelled as modeled/uncertain
- [ ] Small-cell suppression applied
- [ ] No fraud language; benign-explanations checklist present
- [ ] Legal review done for audience and jurisdiction
- [ ] Access list reviewed; export log reviewed
- [ ] Sentiment bias audit (language, region, source skew)

## 9. Incident response
Detect (alerts) → contain (revoke keys, disable exports) → assess → notify (as legally required) → remediate → post-mortem.
