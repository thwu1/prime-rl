A set of simplified U.S. Internal Revenue Code statutes are provided in `/app/statutes/`. Twelve taxpayer scenarios are provided as Prolog fact files in `/app/cases/` (e.g., `/app/cases/case_01.pl`).

Build a SWI-Prolog program at `/app/tax_engine.pl` that implements a statutory tax reasoning engine. The engine must expose a predicate `compute_tax(TaxOwed)` that, when loaded together with a case file, computes the integer dollar amount of tax owed for that taxpayer scenario.

The statutes define interacting rules for: gross income computation with exclusions (Section 61), filing status determination with priority ordering (Section 2), adjusted gross income and deduction selection (Sections 62/63), dependent qualification and personal exemption phase-out (Sections 151/152), progressive tax bracket application (Section 1), and child tax credit with income phase-out (Section 24).

Each case file defines Prolog facts using these predicates: `taxpayer/3`, `spouse/3`, `marital_status/1`, `filing_preference/1`, `spouse_death_year/1`, `income/2`, `above_the_line/2`, `total_itemized/1`, `dependent/9`, and `maintains_parent_household/1`. Examine the case files to understand the schema.

The engine will be invoked as:
```
swipl -g "consult('/app/tax_engine'), consult('/app/cases/case_XX'), compute_tax(X), write(X), halt" -t "halt"
```

The tax year is 2024. All final tax amounts must be whole dollar integers (truncated/floored). The engine must produce correct results for all 12 case files.