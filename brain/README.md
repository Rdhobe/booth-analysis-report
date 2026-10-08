# UPBI Brain Folder
**Working name:** UPBI (Uttar Pradesh Booth Intelligence)

This folder is the single source of truth for the project. Any AI assistant or contributor should read it before writing code.

## Load order
| # | File | Purpose |
|---|------|---------|
| 1 | `BRAIN.md` | Mission, scope, decisions log, open questions. Start here. |
| 2 | `PRD.md` | What we build, for whom, success metrics, non-goals |
| 3 | `ARCHITECTURE.md` | Pipeline, repo layout, data model, tech stack |
| 4 | `DATA_SOURCES.md` | Where each dataset comes from, quirks, licensing |
| 5 | `MODELS.md` | Sentiment, caste-composition estimation, anomaly engine specs |
| 6 | `DESIGN.md` | Dashboard UX, map encoding, color scales |
| 7 | `RULES.md` | Coding standards and hard project rules |
| 8 | `SECURITY.md` | Privacy, legal, ethics, threat model |
| 9 | `TASKS.md` | Phased backlog with acceptance criteria |
| 10 | `GLOSSARY.md` | Terms and abbreviations |
| 11 | `CHANGELOG.md` | Dated change log (newest first) — updated with every change |
| 12 | `PLAN.md` | Web server + dashboard track (serving plan, phases, decisions) |

Other files here (`*.docx`, `*.html`) are reference inputs, not source of truth.

Rule: if code and docs disagree, fix whichever is wrong in the same commit.
