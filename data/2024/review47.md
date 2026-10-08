# REVIEW47 - manual review of the 47 quarantined files

Source: `data/2024/bulk_convert_report.csv` (status REVIEW only). Generated read-only: no PDF, XLSX or report CSV was modified by this pass.

The strategies (tried in order, first full pass wins):

S1 base — re-extract with the patched converter (footer-row recovery) and validate. No data touched. Fixes files whose only problem was page-footer rows diverted to summary.
S2 zero-fill — vote-range None→0 (max 2 per row), lead text None→Unknown. Refuses blank (all-None) rows and >2 gaps. Accepted only if row sums + EVM then fully pass.
S3 trim — drops trailing empty candidate names (candidate count −1, trailer shifts left). For files where a phantom empty name pushed the trailer one column right.
S4 trim-swap — S3 plus swaps the Total/NOTA trailer columns, for the variant layout with Total before NOTA plus a trailing grand-total column (Deoria-1712).

Rule applied: vote-range `None` -> `0`, lead text `None` -> `Unknown` - but only where the full validation (row sums + EVM totals where present) passes afterwards. Blank (all-None) rows are never zero-filled.

| # | File | Booths | Class | Retry outcome | Detail |
|---|------|--------|-------|---------------|--------|
| 1 | `Azamgarh\2024091370.pdf` | 376 | NONE_CELLS | S2-zero-fill -> WOULD_CONVERT_S2 | row 111 col 7: None -> 0; row 368 col 7: None -> 0 |
| 2 | `Bijnor\2024091314.pdf` | 322 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 3 | `Bijnor\2024091317.pdf` | 392 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 4 | `Bijnor\2024091318.pdf` | 362 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 5 | `Bijnor\2024091322-1.pdf` | 439 | EVM_SHORTFALL_GAPS | - -> REVIEW STILL | S2-filled but still invalid (14): EVM total mismatch col 2: booth-sum=86914 vs evm=89429 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=16[28, 56, 84, 112, 140, 168, 196, 224, 252, 280, 308, 336] starts=1 evm=Y evm_label=Total EVM Votes |
| 6 | `Bijnor\2024091322.pdf` | 364 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 7 | `Bijnor\2024091338.pdf` | 353 | EVM_SHORTFALL_GAPS | - -> REVIEW STILL | S2-filled but still invalid (14): EVM total mismatch col 2: booth-sum=84686 vs evm=88691 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=13[28, 56, 84, 112, 140, 168, 196, 224, 252, 280, 308, 336] starts=1 evm=Y evm_label=Total EVM Votes |
| 8 | `Bijnor\2024091363.pdf` | 348 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 9 | `Budaun\2024091311.pdf` | 389 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 10 | `Budaun\2024091347.pdf` | 394 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 11 | `Budaun\2024091355.pdf` | 455 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 12 | `Budaun\2024091376.pdf` | 436 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 13 | `Budaun\2024091381.pdf` | 443 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 14 | `Chandauli\2024091312.pdf` | 357 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 15 | `Chandauli\2024091314.pdf` | 359 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 16 | `Chandauli\2024091362.pdf` | 407 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 17 | `Deoria\2024091712.pdf` | 344 | TRAILER_GEOMETRY | S4-trim-swap -> WOULD_CONVERT_S4 |  |
| 18 | `Deoria\2024091722-1.pdf` | 353 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (679): row 1: sum(cands)=1112 != valid=0 S3-trim tried, still invalid (679): row 1: sum(cands)=560 != valid=552 none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Mkd eri=ksa ij vfHkfyf[kr erksa dh la[;k |
| 19 | `Deoria\2024091729.pdf` | 384 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (736): row 1: sum(cands)=623 != valid=4 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=Y evm_label=Total EVM Votes |
| 20 | `Deoria\2024091783-1.pdf` | 361 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (691): row 1: sum(cands)=421 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=Y evm_label=Total EVM Votes |
| 21 | `Deoria\2024091783.pdf` | 348 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (646): row 1: sum(cands)=486 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=Y evm_label=Total EVM Votes |
| 22 | `Gautam Buddha Nagar\2024091327.pdf` | 432 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (864): row 1: sum(cands)=567 != valid=0 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label= |
| 23 | `Gautam Buddha Nagar\2024091334.pdf` | 398 | BLANK_ROWS_MANUAL | - -> REVIEW STILL | S2-refused: row 327 blank (all votes empty) S3-n/a: no trailing empty candidate name. none=[] blank=['327'] smalldiff=[] bad=[] merged=[] gaps=0[] starts=1 evm=N evm_label=Total No. Of Votes recorded at polling S |
| 24 | `Gautam Buddha Nagar\2024091380.pdf` | 433 | NONE_CELLS | - -> REVIEW STILL | S2-filled but still invalid (866): row 1: sum(cands)=598 != valid=0 S3-n/a: no trailing empty candidate name. none=[('34', 1), ('199', 1)] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label= |
| 25 | `Ghaziabad\2025052633.pdf` | 492 | EVM_SHORTFALL_GAPS | - -> REVIEW STILL | S2-filled but still invalid (15): EVM total mismatch col 2: booth-sum=133095 vs evm=137206 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=14[35, 70, 105, 140, 175, 210, 245, 280, 315, 350, 385, 420] starts=1 evm=Y evm_label=Total EVM Votes |
| 26 | `Kanpur Nagar\2024091712.pdf` | 416 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 27 | `Kanpur Nagar\2024091717.pdf` | 452 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 28 | `Kanpur Nagar\2024091729.pdf` | 340 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 29 | `Kanpur Nagar\2024091747.pdf` | 366 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 30 | `Kheri\2024091711.pdf` | 1817 | MULTI_AC_MANUAL | - -> REVIEW STILL | S2-filled but still invalid (15): EVM total mismatch col 2: booth-sum=429860 vs evm=84845 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=14[31, 62, 93, 124, 155, 186, 217, 248, 279, 310, 341, 372] starts=5 evm=Y evm_label=Total EVM Votes |
| 31 | `Kheri\2024091738.pdf` | 1848 | MULTI_AC_MANUAL | - -> REVIEW STILL | S2-filled but still invalid (14): EVM total mismatch col 2: booth-sum=521954 vs evm=104631 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=0[] starts=5 evm=Y evm_label=Total EVM Votes |
| 32 | `Lucknow\2024091312.pdf` | 339 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 33 | `Moradabad\2024091368.pdf` | 436 | SMALL_DIFF_MANUAL | - -> REVIEW STILL | S2-filled but still invalid (7): row 245: sum(cands)=647 != valid=650 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=['245', '246', '247', '249', '250', '252', '254'] bad=[] merged=[] gaps=0[] starts=1 evm=N evm_label=Mkd eri=ksa ij vfHkfyf[kr erksa dh la[;k |
| 34 | `Moradabad\2024091386.pdf` | 409 | MERGED_SERIAL_MANUAL | - -> REVIEW STILL | S2-filled but still invalid (19): row 33: sum(cands)=341297 != valid=442277 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['33', '3344', '6666', '9988', '113300', '116622'] merged=['3344', '6666', '9988', '113300'] gaps=338447[3, 34, 66, 98, 130, 162, 194, 226, 258, 290, 322, 354] starts=1 evm=N evm_label=add |
| 35 | `Saharanpur\2024091723.pdf` | 384 | EVM_SHORTFALL_GAPS | - -> REVIEW STILL | S2-filled but still invalid (17): EVM total mismatch col 2: booth-sum=114787 vs evm=117901 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=11[33, 66, 99, 132, 165, 198, 231, 264, 297, 330, 363] starts=1 evm=Y evm_label=Total EVM Votes |
| 36 | `Sambhal\2024091340.pdf` | 436 | SMALL_DIFF_MANUAL | - -> REVIEW STILL | S2-filled but still invalid (7): row 245: sum(cands)=647 != valid=650 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=['245', '246', '247', '249', '250', '252', '254'] bad=[] merged=[] gaps=0[] starts=1 evm=N evm_label=Mkd eri=ka s ij vfHkfyf[kr erksa dh la[; |
| 37 | `Siddharthnagar\2024091358.pdf` | 411 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (772): row 1: sum(cands)=715 != valid=2 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round |
| 38 | `Siddharthnagar\2024091364.pdf` | 410 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (772): row 1: sum(cands)=417 != valid=0 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round |
| 39 | `Siddharthnagar\2024091384.pdf` | 451 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (831): row 1: sum(cands)=531 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round |
| 40 | `Siddharthnagar\2024091392.pdf` | 501 | TRAILER_GEOMETRY | - -> REVIEW STILL | S2-filled but still invalid (962): row 1: sum(cands)=558 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round |
| 41 | `Varanasi\2024091311-1.pdf` | 404 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 42 | `Varanasi\2024091341.pdf` | 410 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 43 | `Varanasi\2024091367.pdf` | 370 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 44 | `Varanasi\2024091373.pdf` | 328 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 45 | `Varanasi\2024091394.pdf` | 397 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 46 | `Varanasi\2025022811.pdf` | 380 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |
| 47 | `Varanasi\2025022859.pdf` | 365 | FOOTER_RECOVERED | S1-base -> WOULD_CONVERT_S1 | gaps=0[] starts=1 evm=Y |

## Per-file notes

### `Azamgarh\2024091370.pdf`

- booths=376 ncands=9 class=NONE_CELLS
- retry: S2-zero-fill -> WOULD_CONVERT_S2
- detail: row 111 col 7: None -> 0; row 368 col 7: None -> 0

### `Bijnor\2024091314.pdf`

- booths=322 ncands=6 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Bijnor\2024091317.pdf`

- booths=392 ncands=6 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Bijnor\2024091318.pdf`

- booths=362 ncands=6 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Bijnor\2024091322-1.pdf`

- booths=439 ncands=11 class=EVM_SHORTFALL_GAPS
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (14): EVM total mismatch col 2: booth-sum=86914 vs evm=89429 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=16[28, 56, 84, 112, 140, 168, 196, 224, 252, 280, 308, 336] starts=1 evm=Y evm_label=Total EVM Votes
- residual errors: EVM total mismatch col 2: booth-sum=86914 vs evm=89429; EVM total mismatch col 3: booth-sum=40563 vs evm=41958; EVM total mismatch col 4: booth-sum=1922 vs evm=1996; EVM total mismatch col 5: booth-sum=85165 vs evm=88438

### `Bijnor\2024091322.pdf`

- booths=364 ncands=6 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Bijnor\2024091338.pdf`

- booths=353 ncands=11 class=EVM_SHORTFALL_GAPS
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (14): EVM total mismatch col 2: booth-sum=84686 vs evm=88691 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=13[28, 56, 84, 112, 140, 168, 196, 224, 252, 280, 308, 336] starts=1 evm=Y evm_label=Total EVM Votes
- residual errors: EVM total mismatch col 2: booth-sum=84686 vs evm=88691; EVM total mismatch col 3: booth-sum=28093 vs evm=29149; EVM total mismatch col 4: booth-sum=1573 vs evm=1621; EVM total mismatch col 5: booth-sum=76096 vs evm=78075

### `Bijnor\2024091363.pdf`

- booths=348 ncands=6 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Budaun\2024091311.pdf`

- booths=389 ncands=11 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Budaun\2024091347.pdf`

- booths=394 ncands=11 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Budaun\2024091355.pdf`

- booths=455 ncands=11 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Budaun\2024091376.pdf`

- booths=436 ncands=11 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Budaun\2024091381.pdf`

- booths=443 ncands=11 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Chandauli\2024091312.pdf`

- booths=357 ncands=10 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Chandauli\2024091314.pdf`

- booths=359 ncands=10 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Chandauli\2024091362.pdf`

- booths=407 ncands=10 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Deoria\2024091712.pdf`

- booths=344 ncands=9 class=TRAILER_GEOMETRY
- retry: S4-trim-swap -> WOULD_CONVERT_S4

### `Deoria\2024091722-1.pdf`

- booths=353 ncands=10 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (679): row 1: sum(cands)=1112 != valid=0 S3-trim tried, still invalid (679): row 1: sum(cands)=560 != valid=552 none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Mkd eri=ksa ij vfHkfyf[kr erksa dh la[;k
- residual errors: row 1: sum(cands)=1112 != valid=0; row 1: valid 0+nota 0 != total 8; row 2: sum(cands)=1154 != valid=0; row 2: valid 0+nota 0 != total 8

### `Deoria\2024091729.pdf`

- booths=384 ncands=6 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (736): row 1: sum(cands)=623 != valid=4 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=Y evm_label=Total EVM Votes
- residual errors: row 1: sum(cands)=623 != valid=4; row 1: valid 4+nota 0 != total 2; row 2: sum(cands)=625 != valid=2; row 2: valid 2+nota 0 != total 7

### `Deoria\2024091783-1.pdf`

- booths=361 ncands=6 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (691): row 1: sum(cands)=421 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=Y evm_label=Total EVM Votes
- residual errors: row 1: sum(cands)=421 != valid=1; row 1: valid 1+nota 0 != total 3; row 2: sum(cands)=472 != valid=1; row 2: valid 1+nota 0 != total 6

### `Deoria\2024091783.pdf`

- booths=348 ncands=6 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (646): row 1: sum(cands)=486 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=Y evm_label=Total EVM Votes
- residual errors: row 1: sum(cands)=486 != valid=1; row 1: valid 1+nota 0 != total 6; row 2: sum(cands)=453 != valid=0; row 2: valid 0+nota 0 != total 3

### `Gautam Buddha Nagar\2024091327.pdf`

- booths=432 ncands=15 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (864): row 1: sum(cands)=567 != valid=0 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=
- residual errors: row 1: sum(cands)=567 != valid=0; row 1: valid 0+nota 0 != total 567; row 2: sum(cands)=619 != valid=1; row 2: valid 1+nota 0 != total 620

### `Gautam Buddha Nagar\2024091334.pdf`

- booths=398 ncands=15 class=BLANK_ROWS_MANUAL
- retry: - -> REVIEW STILL
- detail: S2-refused: row 327 blank (all votes empty) S3-n/a: no trailing empty candidate name. none=[] blank=['327'] smalldiff=[] bad=[] merged=[] gaps=0[] starts=1 evm=N evm_label=Total No. Of Votes recorded at polling S
- residual errors: row 327: non-numeric vote cell: [None, None, None, None, None, None, None, None, None, None, None, None, None, None, None]

### `Gautam Buddha Nagar\2024091380.pdf`

- booths=433 ncands=15 class=NONE_CELLS
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (866): row 1: sum(cands)=598 != valid=0 S3-n/a: no trailing empty candidate name. none=[('34', 1), ('199', 1)] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=
- residual errors: row 1: sum(cands)=598 != valid=0; row 1: valid 0+nota 0 != total 598; row 2: sum(cands)=472 != valid=3; row 2: valid 3+nota 0 != total 475

### `Ghaziabad\2025052633.pdf`

- booths=492 ncands=14 class=EVM_SHORTFALL_GAPS
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (15): EVM total mismatch col 2: booth-sum=133095 vs evm=137206 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=14[35, 70, 105, 140, 175, 210, 245, 280, 315, 350, 385, 420] starts=1 evm=Y evm_label=Total EVM Votes
- residual errors: EVM total mismatch col 2: booth-sum=133095 vs evm=137206; EVM total mismatch col 3: booth-sum=71700 vs evm=73950; EVM total mismatch col 4: booth-sum=13738 vs evm=13983; EVM total mismatch col 6: booth-sum=102 vs evm=104

### `Kanpur Nagar\2024091712.pdf`

- booths=416 ncands=9 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Kanpur Nagar\2024091717.pdf`

- booths=452 ncands=9 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Kanpur Nagar\2024091729.pdf`

- booths=340 ncands=9 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Kanpur Nagar\2024091747.pdf`

- booths=366 ncands=9 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Kheri\2024091711.pdf`

- booths=1817 ncands=12 class=MULTI_AC_MANUAL
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (15): EVM total mismatch col 2: booth-sum=429860 vs evm=84845 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=14[31, 62, 93, 124, 155, 186, 217, 248, 279, 310, 341, 372] starts=5 evm=Y evm_label=Total EVM Votes
- residual errors: EVM total mismatch col 2: booth-sum=429860 vs evm=84845; EVM total mismatch col 3: booth-sum=425510 vs evm=90977; EVM total mismatch col 4: booth-sum=179383 vs evm=35417; EVM total mismatch col 5: booth-sum=3448 vs evm=840

### `Kheri\2024091738.pdf`

- booths=1848 ncands=11 class=MULTI_AC_MANUAL
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (14): EVM total mismatch col 2: booth-sum=521954 vs evm=104631 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=0[] starts=5 evm=Y evm_label=Total EVM Votes
- residual errors: EVM total mismatch col 2: booth-sum=521954 vs evm=104631; EVM total mismatch col 3: booth-sum=555277 vs evm=97788; EVM total mismatch col 4: booth-sum=110122 vs evm=24272; EVM total mismatch col 5: booth-sum=2298 vs evm=493

### `Lucknow\2024091312.pdf`

- booths=339 ncands=10 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Moradabad\2024091368.pdf`

- booths=436 ncands=12 class=SMALL_DIFF_MANUAL
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (7): row 245: sum(cands)=647 != valid=650 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=['245', '246', '247', '249', '250', '252', '254'] bad=[] merged=[] gaps=0[] starts=1 evm=N evm_label=Mkd eri=ksa ij vfHkfyf[kr erksa dh la[;k
- residual errors: row 245: sum(cands)=647 != valid=650; row 246: sum(cands)=693 != valid=695; row 247: sum(cands)=684 != valid=685; row 249: sum(cands)=504 != valid=501

### `Moradabad\2024091386.pdf`

- booths=409 ncands=12 class=MERGED_SERIAL_MANUAL
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (19): row 33: sum(cands)=341297 != valid=442277 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['33', '3344', '6666', '9988', '113300', '116622'] merged=['3344', '6666', '9988', '113300'] gaps=338447[3, 34, 66, 98, 130, 162, 194, 226, 258, 290, 322, 354] starts=1 evm=N evm_label=add
- residual errors: row 33: sum(cands)=341297 != valid=442277; row 33: valid 442277+nota 33 != total 443300; row 3344: sum(cands)=236863 != valid=0; row 3344: valid 0+nota 88 != total 339911

### `Saharanpur\2024091723.pdf`

- booths=384 ncands=14 class=EVM_SHORTFALL_GAPS
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (17): EVM total mismatch col 2: booth-sum=114787 vs evm=117901 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=[] merged=[] gaps=11[33, 66, 99, 132, 165, 198, 231, 264, 297, 330, 363] starts=1 evm=Y evm_label=Total EVM Votes
- residual errors: EVM total mismatch col 2: booth-sum=114787 vs evm=117901; EVM total mismatch col 3: booth-sum=98010 vs evm=100986; EVM total mismatch col 4: booth-sum=22082 vs evm=22766; EVM total mismatch col 5: booth-sum=231 vs evm=235

### `Sambhal\2024091340.pdf`

- booths=436 ncands=12 class=SMALL_DIFF_MANUAL
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (7): row 245: sum(cands)=647 != valid=650 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=['245', '246', '247', '249', '250', '252', '254'] bad=[] merged=[] gaps=0[] starts=1 evm=N evm_label=Mkd eri=ka s ij vfHkfyf[kr erksa dh la[;
- residual errors: row 245: sum(cands)=647 != valid=650; row 246: sum(cands)=693 != valid=695; row 247: sum(cands)=684 != valid=685; row 249: sum(cands)=504 != valid=501

### `Siddharthnagar\2024091358.pdf`

- booths=411 ncands=5 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (772): row 1: sum(cands)=715 != valid=2 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round
- residual errors: row 1: sum(cands)=715 != valid=2; row 1: valid 2+nota 0 != total 8; row 2: sum(cands)=322 != valid=0; row 2: valid 0+nota 0 != total 3

### `Siddharthnagar\2024091364.pdf`

- booths=410 ncands=5 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (772): row 1: sum(cands)=417 != valid=0 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round
- residual errors: row 1: sum(cands)=417 != valid=0; row 1: valid 0+nota 0 != total 10; row 2: sum(cands)=358 != valid=0; row 2: valid 0+nota 0 != total 1

### `Siddharthnagar\2024091384.pdf`

- booths=451 ncands=5 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (831): row 1: sum(cands)=531 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round
- residual errors: row 1: sum(cands)=531 != valid=1; row 1: valid 1+nota 0 != total 2; row 2: sum(cands)=606 != valid=2; row 2: valid 2+nota 0 != total 1

### `Siddharthnagar\2024091392.pdf`

- booths=501 ncands=5 class=TRAILER_GEOMETRY
- retry: - -> REVIEW STILL
- detail: S2-filled but still invalid (962): row 1: sum(cands)=558 != valid=1 S3-n/a: no trailing empty candidate name. none=[] blank=[] smalldiff=[] bad=['1', '2', '3', '4', '5', '6'] merged=[] gaps=0[] starts=1 evm=N evm_label=Special Round
- residual errors: row 1: sum(cands)=558 != valid=1; row 1: valid 1+nota 0 != total 10; row 2: sum(cands)=312 != valid=0; row 2: valid 0+nota 0 != total 3

### `Varanasi\2024091311-1.pdf`

- booths=404 ncands=7 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Varanasi\2024091341.pdf`

- booths=410 ncands=7 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Varanasi\2024091367.pdf`

- booths=370 ncands=7 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Varanasi\2024091373.pdf`

- booths=328 ncands=7 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Varanasi\2024091394.pdf`

- booths=397 ncands=7 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Varanasi\2025022811.pdf`

- booths=380 ncands=10 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

### `Varanasi\2025022859.pdf`

- booths=365 ncands=10 class=FOOTER_RECOVERED
- retry: S1-base -> WOULD_CONVERT_S1
- detail: gaps=0[] starts=1 evm=Y

