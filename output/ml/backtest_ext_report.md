# Extended backtest

Train: assembly 2012 + Lok Sabha 2009/2014 -> assembly 2017.  Test: assembly 2017 + Lok Sabha 2014/2019 -> assembly 2022.  399 constituencies in the test.

Average miss in percentage points (lower is better).

| Method | Features | BJP-led | SP/INC | BSP | Mean | 80% within | Lead called right |
|---|---|---|---|---|---|---|---|
| Same as last assembly election | none | 4.86 | 11.67 | 9.82 | 8.79 | 13.6 | 68% |
| Last assembly result plus the Lok Sabha swing | none | 7.62 | 19.62 | 16.94 | 14.72 | 26.87 | 63% |
| Latest Lok Sabha result for the seat | none | 7.81 | 18.99 | 17.92 | 14.91 | 27.06 | 65% |
| Average of last assembly result and latest Lok Sabha | none | 4.29 | 13.39 | 10.42 | 9.37 | 18.53 | 69% |
| CEILING: last result plus true state swing (only known afterwards) | none | 4.61 | 5.87 | 5.0 | 5.16 | 7.83 | 74% |
| Ridge | history only | 6.13 | 11.49 | 7.21 | 8.28 | 13.3 | 62% |
| Ridge | history + Lok Sabha | 6.18 | 13.23 | 7.6 | 9.01 | 14.27 | 62% |
| Ridge | history + Lok Sabha + candidate (after nominations) | 6.25 | 13.22 | 7.48 | 8.98 | 14.15 | 62% |
| Gradient boosting | history only | 7.0 | 12.36 | 6.78 | 8.71 | 13.92 | 62% |
| Gradient boosting | history + Lok Sabha | 6.34 | 11.73 | 6.15 | 8.08 | 12.92 | 66% |
| Gradient boosting | history + Lok Sabha + candidate (after nominations) | 6.34 | 11.69 | 6.21 | 8.08 | 12.92 | 66% |

Best simple baseline: **Same as last assembly election** (mean miss 8.79 pts).
A learned model is promoted only if it beats that on every front by 0.2 pts. Promoted: **False**.

## Cross-section check (not a forward test)

5-fold CV grouped by district inside task B (assembly 2022 as target)

| Method | Features | BJP-led | SP/INC | BSP | Mean |
|---|---|---|---|---|---|
| Ridge | history + Lok Sabha + candidate | 3.81 | 4.66 | 4.12 | 4.2 |
| Ridge | ... plus turnout, electors and 2019 booth-sheet fronts | 3.56 | 4.54 | 4.07 | 4.06 |
| Gradient boosting | history + Lok Sabha + candidate | 3.86 | 4.91 | 4.27 | 4.34 |
| Gradient boosting | ... plus turnout, electors and 2019 booth-sheet fronts | 3.5 | 4.63 | 4.15 | 4.09 |
