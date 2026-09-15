# FINRA Data File Schemas

## Consolidated Short Interest (consolidated_si.csv)

14-field quoted CSV. Bi-monthly reporting under FINRA Rule 4560.

| Field | Type | Description |
|-------|------|-------------|
| accountingYearMonthNumber | int | YYYYMMDD format |
| symbolCode | string | Ticker symbol |
| issueName | string | Security name |
| issuerServicesGroupExchangeCode | string | Exchange code (A=NYSE, R=NNM, E=ARCA, S=OTC, B=AMEX) |
| marketClassCode | string | Market class |
| currentShortPositionQuantity | int | Current reporting period short position |
| previousShortPositionQuantity | int | Previous reporting period short position |
| stockSplitFlag | string/null | Stock split indicator |
| averageDailyVolumeQuantity | int | Average daily trading volume |
| daysToCoverQuantity | float | Days to cover ratio |
| revisionFlag | string/null | Revision indicator |
| changePercent | float | Percentage change from previous period |
| changePreviousNumber | int | Numeric change from previous period |
| settlementDate | date | Settlement date (YYYY-MM-DD) |

## Short Sale Volume Files (pipe-delimited, e.g. fnsq_volume.txt, fnyx_volume.txt)

Daily short sale volume by reporting facility. Pipe-delimited with header row.
Last line is a bare integer record count (not a data row).

| Field | Description |
|-------|-------------|
| Date | YYYYMMDD format |
| Symbol | Ticker symbol |
| ShortVolume | Short sale volume (may contain fractional values) |
| ShortExemptVolume | Short exempt volume |
| TotalVolume | Total trade volume (may contain fractional values) |
| Market | Market codes (B=BATS/Cboe, Q=Nasdaq, N=NYSE) |

Filename convention: `{facilityCode}_volume.txt` where facilityCode identifies the
reporting facility (e.g., FNSQ = FINRA/Nasdaq TRF, FNYX = FINRA/NYSE TRF).

## Threshold Securities List (threshold_list.csv)

Daily Reg SHO threshold securities list. 8-field quoted CSV.

| Field | Description |
|-------|-------------|
| tradeDate | Date (YYYY-MM-DD) |
| issueSymbolIdentifier | Ticker symbol |
| issueName | Security name |
| marketClassCode | Market class (OTC, etc.) |
| thresholdListFlag | NR or R |
| marketCategoryDescription | Market category |
| regShoThresholdFlag | Y/N — Reg SHO threshold security designation |
| rule4320Flag | Y/N — FINRA Rule 4320 designation |
