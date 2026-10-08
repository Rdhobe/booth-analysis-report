# Flatten report - excels moved to year root

Moved 11, skipped 17.

- `data\2024\Pryagraj\264.xlsx` -> `data\2024\264.xlsx`
- `data\2024\Pryagraj\265.xlsx` -> `data\2024\265.xlsx`
- `data\2024\Sambhal\30.xlsx` -> `data\2024\30.xlsx`
- `data\2024\Sambhal\31.xlsx` -> `data\2024\31.xlsx`
- `data\2024\Sambhal\32.xlsx` -> `data\2024\32.xlsx`
- `data\2024\Sitapur\146.xlsx` -> `data\2024\146.xlsx`
- `data\2024\Sitapur\148.xlsx` -> `data\2024\148.xlsx`
- `data\2024\Sitapur\149.xlsx` -> `data\2024\149.xlsx`
- `data\2024\Sitapur\150.xlsx` -> `data\2024\150.xlsx`
- `data\2024\Sitapur\151.xlsx` -> `data\2024\151.xlsx`
- `data\2024\Varanasi\384.xlsx` -> `data\2024\384.xlsx`

## Skipped (left in place)

- `data\2019\Barabanki\271.xls` (collision: 2019/271.xls exists on disk)
- `data\2019\Hapur\58.xls` (collision: 2019/58.xls exists on disk)
- `data\2019\Sambhal\30.xls` (collision: 2019/30.xls exists on disk)
- `data\2019\Sultanpur\184.xls` (collision: 2019/184.xls exists on disk)
- `data\2022\Faizabad\AC271.xls` (collision: 2022/AC271.xls exists on disk)
- `data\2022\Hapur\AC58.xlsx` (collision: 2022/AC58.xlsx exists on disk)
- `data\2022\Sambhal\AC30.xlsx` (collision: 2022/AC30.xlsx exists on disk)
- `data\2022\Sultanpur\AC184.xls` (collision: 2022/AC184.xls exists on disk)
- `data\2024\Barabanki\266.xlsx` (collision: 2024/266.xlsx exists)
- `data\2024\Barabanki\267.xlsx` (collision: 2024/267.xlsx exists)
- `data\2024\Barabanki\268.xlsx` (collision: 2024/268.xlsx exists)
- `data\2024\Barabanki\269.xlsx` (collision: 2024/269.xlsx exists)
- `data\2024\Barabanki\272.xlsx` (collision: 2024/272.xlsx exists)
- `data\2024\Pryagraj\257.xlsx` (collision: 2024/257.xlsx exists)
- `data\2024\Pryagraj\258.xlsx` (collision: 2024/258.xlsx exists)
- `data\2024\Shrawasti\290.xlsx` (collision: 2024/290.xlsx exists)
- `data\2024\Sitapur\152.xlsx` (collision: 2024/152.xlsx exists)

## Locked (close holders and rerun --apply)

- `data\2024\Pryagraj\264.xlsx` (locked - close Excel/other holders and rerun: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\projects\\booth analysis report\\data\\2024\\Pryagraj\\264.xlsx' -> 'C:\\projects\\booth analysis report\\data\\2024\\264.xlsx')
- `data\2024\Pryagraj\265.xlsx` (locked - close Excel/other holders and rerun: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\projects\\booth analysis report\\data\\2024\\Pryagraj\\265.xlsx' -> 'C:\\projects\\booth analysis report\\data\\2024\\265.xlsx')
- `data\2024\Sambhal\30.xlsx` (locked - close Excel/other holders and rerun: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\projects\\booth analysis report\\data\\2024\\Sambhal\\30.xlsx' -> 'C:\\projects\\booth analysis report\\data\\2024\\30.xlsx')
- `data\2024\Sambhal\31.xlsx` (locked - close Excel/other holders and rerun: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\projects\\booth analysis report\\data\\2024\\Sambhal\\31.xlsx' -> 'C:\\projects\\booth analysis report\\data\\2024\\31.xlsx')

## Skipped duplicates: content vs winner

- CONFLICT-differs `data\2019\Barabanki\271.xls` vs `data\2017\271.xls`
- CONFLICT-differs `data\2019\Hapur\58.xls` vs `data\2017\58.xls`
- CONFLICT-differs `data\2019\Sambhal\30.xls` vs `data\2017\30.xls`
- CONFLICT-differs `data\2019\Sultanpur\184.xls` vs `data\2017\184.xls`
- IDENTICAL `data\2022\Faizabad\AC271.xls` vs `data\2022\AC271.xls`
- IDENTICAL `data\2022\Hapur\AC58.xlsx` vs `data\2022\AC58.xlsx`
- IDENTICAL `data\2022\Sambhal\AC30.xlsx` vs `data\2022\AC30.xlsx`
- IDENTICAL `data\2022\Sultanpur\AC184.xls` vs `data\2022\AC184.xls`
- CONFLICT-differs `data\2024\Barabanki\266.xlsx` vs `data\2024\266.xlsx`
- CONFLICT-differs `data\2024\Barabanki\267.xlsx` vs `data\2024\267.xlsx`
- CONFLICT-differs `data\2024\Barabanki\268.xlsx` vs `data\2024\268.xlsx`
- CONFLICT-differs `data\2024\Barabanki\269.xlsx` vs `data\2024\269.xlsx`
- CONFLICT-differs `data\2024\Barabanki\272.xlsx` vs `data\2024\272.xlsx`
- CONFLICT-differs `data\2024\Pryagraj\257.xlsx` vs `data\2024\257.xlsx`
- CONFLICT-differs `data\2024\Pryagraj\258.xlsx` vs `data\2024\258.xlsx`
- CONFLICT-differs `data\2024\Shrawasti\290.xlsx` vs `data\2024\290.xlsx`
- CONFLICT-differs `data\2024\Sitapur\152.xlsx` vs `data\2024\152.xlsx`

## Filemap stale-ref corrections (A6-verified)

- `data/2024/Pryagraj/2024091346.pdf` : `data/2024/Pryagraj/2024091346.xlsx` -> `data/2024/Pryagraj/257.xlsx`
- `data/2024/Pryagraj/2024091370.pdf` : `data/2024/Pryagraj/2024091370.xlsx` -> `data/2024/Pryagraj/264.xlsx`
- `data/2024/Pryagraj/2024091379.pdf` : `data/2024/Pryagraj/2024091379.xlsx` -> `data/2024/Pryagraj/265.xlsx`
- `data/2024/Pryagraj/2024091397.pdf` : `data/2024/Pryagraj/2024091397.xlsx` -> `data/2024/Pryagraj/258.xlsx`
- `data/2024/Sambhal/2024091320.pdf` : `data/2024/Sambhal/2024091320.xlsx` -> `data/2024/Sambhal/30.xlsx`
- `data/2024/Sambhal/2024091351.pdf` : `data/2024/Sambhal/2024091351.xlsx` -> `data/2024/Sambhal/31.xlsx`
- `data/2024/Sambhal/2024091384.pdf` : `data/2024/Sambhal/2024091384.xlsx` -> `data/2024/Sambhal/32.xlsx`

## Stale quarantine sidecars swept (bulk=OK + final xlsx present)

- `data\2024\Pryagraj\2024091346.REVIEW.xlsx` (bulk=OK + final xlsx present)
- `data\2024\Pryagraj\2024091370.REVIEW.xlsx` (bulk=OK + final xlsx present)
- `data\2024\Pryagraj\2024091379.REVIEW.xlsx` (bulk=OK + final xlsx present)
- `data\2024\Pryagraj\2024091397.REVIEW.xlsx` (bulk=OK + final xlsx present)
- `data\2024\Sambhal\2024091320.REVIEW.xlsx` (bulk=OK + final xlsx present)
- `data\2024\Sambhal\2024091351.REVIEW.xlsx` (bulk=OK + final xlsx present)
- `data\2024\Sambhal\2024091384.REVIEW.xlsx` (bulk=OK + final xlsx present)
