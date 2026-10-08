# EXCEL ↔ PDF map (2024)

- `data/2024/EXCEL/` — 179 xlsx, 177 distinct ACs (AC 29 and 67 have 2 files each)
- `data/2024/PDF/` — 390 PDFs across 355 ACs, rotation done
- ACs with **both**: **176** (done — verify, don't reconvert; +1 bulk Hin 2026-10-08)
- PDF but **no xlsx** (remaining to convert): **179**
- xlsx but **no PDF**: **1** — AC 37 (keep, source PDF absent)

## Convert queue (179, easiest first)

### 1. Eng, single file — 48 (bulk run 2026-10-08: 4 OK, rest SCANNED/REVIEW/LEGACY/COMPLEX)
1, 3, 4, 5, 6, 36, 46, 47, 48, 49, 52, 63, 65, 66, 109, 137, 141,
162, 163, 164, 165, 166, 167, 177, 179, 180, 182, 187, 188, 189,
191, 221, 228, 229, 270, 271, 273, 274, 275, 279, 282, 283, 285,
286, 395, 396, 397, 398, 399

### 2. Hin, single file — 116 (bulk run 2026-10-08: 1 OK (326), rest below)
8, 9, 10, 11, 12, 13, 14, 15, 16, 19, 25, 26, 27, 28, 33, 39, 40,
41, 42, 44, 45, 50, 51, 53, 57, 59, 60, 64, 69, 70, 96, 98, 99,
104, 105, 118, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136,
153, 154, 157, 158, 159, 160, 161, 193, 194, 195, 199, 200, 201,
204, 205, 206, 207, 208, 284, 293, 295, 296, 297, 298, 299, 300,
301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 313,
314, 315, 316, 317, 318, 319, 325, 340, 343, 346, 347, 348,
349, 350, 352, 357, 359, 360, 361, 362, 363, 373, 374, 375, 376,
377, 378, 379, 392, 393, 394

### 3. Duplicate PDFs — 15 (dedup first, then queue by winner)
2, 43, 58, 68, 81, 82, 83, 84, 85, 95, 103, 192, 209, 287, 288

## Done (both Excel + PDF — 176, verify only)

7, 17, 18, 20, 21, 22, 23, 24, 29, 30, 31, 32, 54, 55, 56, 61, 62,
67, 71, 72, 73, 74, 75, 76, 77, 86, 87, 88, 89, 90, 91, 92, 93, 94,
106, 111, 112, 113, 114, 115, 116, 117, 119, 120, 121, 122, 123, 124,
125, 126, 146, 148, 149, 150, 151, 152, 168, 169, 170, 171, 172, 173,
174, 175, 176, 178, 184, 185, 186, 196, 197, 198, 210, 211, 212, 213,
214, 215, 216, 217, 218, 222, 223, 224, 225, 231, 232, 233, 234, 235,
237, 238, 239, 240, 241, 242, 243, 244, 247, 248, 249, 250, 254, 255,
256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266, 267, 268, 269,
272, 276, 277, 278, 280, 281, 289, 290, 291, 292, 294, 320, 321, 322,
323, 324, 326, 327, 328, 329, 330, 331, 332, 333, 334, 335, 337, 338, 339,
344, 345, 353, 354, 355, 356, 358, 364, 365, 366, 367, 368, 369, 370,
371, 372, 380, 381, 382, 383, 384, 385, 386, 387, 388, 389, 390, 391

## Bulk Eng run 2026-10-08 (59 files, report `PDF/bulk_eng_report.csv`)

- OK 4 → filed to EXCEL as 17/380/381/382.xlsx
- REVIEW 3 (quarantined `.REVIEW.xlsx` in PDF/): 137, 141 (booth sums ~5× EVM
  totals — suspect multi-AC concatenation, split per AC before use), 63
  (blank row 327, single unparsed row)
- LEGACY_SKIP 3: 65, 66, 68 (DevLys-era fonts — manual/decoder pass)
- COMPLEX_SKIP 2: 221 (unmapped glyphs), 2Eng.pdf (no usable tables) — manual
- SCANNED 48 → OCR queue (GPU/Colab): 1, 3, 4, 5, 6, 36, 46, 47, 48, 49, 52,
  109, 162, 163, 164, 165, 166, 167, 177, 179, 180, 182, 187, 188, 189, 191,
  192, 228, 229, 270, 271, 273, 274, 275, 279, 282, 283, 285, 286, 287, 288,
  2Eng (2), 2Eng (3), 395, 396, 397, 398, 399

## Bulk Hin run 2026-10-08 (117 files, log `build_log2.txt`, report `PDF/bulk_hin_report.csv`)

- OK 1 → filed to EXCEL as 326.xlsx
- REVIEW 6 (quarantined `.REVIEW.xlsx` in PDF/): 302, 303, 304, 306, 64, 70
  (trailer-column shift: sum(cands)≈total but valid≈0 — trailer-geometry
  variant, needs S4-type retry)
- LEGACY_SKIP 38 (DevLys-era fonts — manual/decoder pass)
- SCANNED 67 → OCR queue (GPU/Colab) with the 48 Eng scans
- COMPLEX_SKIP 5: 343, 348, 350, 352, 69 (unmapped glyphs — manual)

## Notes

- AC 326: VERIFIED by hand, candidate names added, filed as `EXCEL/326.xlsx`.
- AC 31: `31RHin.pdf` was already corrupt before rotation — BROKEN, nothing
  to do. `31Hin.pdf` is the usable copy (xlsx exists, in Done list).
- AC 29 and 67 have 2 xlsx each in EXCEL — keep both until verified identical.
- AC 37 has `EXCEL/37.xlsx` but no PDF — converted from a source that is no
  longer in `PDF/`; keep as-is.
- 48 ACs have neither PDF nor xlsx (see `missing_AC.md` — unchanged, PDFs untouched).
