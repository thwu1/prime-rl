# FHIRPath Quantity Evaluation Semantics

This document describes the correct behavior for quantity evaluation,
based on the FHIRPath 2.0.0 specification.

## Unit Systems

### Calendar Durations (unquoted)
year(s), month(s), week(s), day(s), hour(s), minute(s), second(s), millisecond(s)

### UCUM Units (single-quoted in expressions)
'kg', 'g', 'mg', 'm', 'km', 'cm', 's', 'min', 'h', 'd', 'wk', 'ms', '1'

The UCUM time units and their second-equivalents:
- 's' → 1 second
- 'min' → 60 seconds
- 'h' → 3600 seconds
- 'd' → 86400 seconds
- 'wk' → 604800 seconds
- 'ms' → 0.001 seconds

## Arithmetic Rules

### Addition/Subtraction of Calendar Durations
When adding or subtracting two calendar durations of different units:
- The result uses the **finer-grained** (smaller) unit
- **Year/month conversions**: 1 year = 12 months exactly (NOT seconds-based)
- **All other calendar conversions**: use second-equivalents

Example: `1 year + 6 months` → convert year to months: 12 + 6 = `18 months`
Example: `1 hour + 30 minutes` → convert via seconds: 3600 + 1800 = 5400s → `90 minutes`

### Addition/Subtraction of UCUM Units
Both units must have compatible dimensions. Result uses the left operand's unit.

### Addition/Subtraction: Mixed Calendar/UCUM
When one operand is a calendar duration and the other is a UCUM time unit:
- Calendar **above-week** (year, month) ± any UCUM → incompatible (`{}`)
- Calendar **at-or-below-week** ± UCUM time → convert both operands to seconds,
  compute the result, and return it in the **left operand's unit system**:
  - If the left operand is calendar: result uses that calendar unit with
    appropriate singular/plural form (singular for ±1, plural otherwise)
  - If the left operand is UCUM: result uses that UCUM unit
- Calendar ± UCUM non-time (e.g., `'kg'`) → incompatible (`{}`)
- UCUM non-time ± calendar → incompatible (`{}`)

Example: `1 minute + 30 's'` → (60 + 30) / 60 = `1.5 minutes`
Example: `1 'h' + 30 minutes` → (3600 + 1800) / 3600 = `1.5 'h'`
Example: `1 day - 12 'h'` → (86400 - 43200) / 86400 = `0.5 days`

### Multiplication
- Quantity × number (or reverse): scale the value, keep the unit
- UCUM × UCUM: compound unit using `.` separator (e.g., `'kg.m'`)
- Calendar × anything: returns empty

### Division
- Quantity / number: scale the value, keep the unit
- Number / quantity: result unit is `'1/<unit>'` (e.g., `20 / 5 'kg'` → `4 '1/kg'`)
- UCUM / UCUM same dimension: dimensionless result (unit `'1'`)
- UCUM / UCUM different dimension: compound unit using `/` separator
- Calendar ÷ anything: returns empty
- Division by zero: returns empty

## Comparison Rules

### Same-system comparison
Two calendar durations or two UCUM quantities of compatible dimensions
are always comparable.

### Calendar duration year/month comparison
Uses the factor 1 year = 12 months.

### Calendar duration other comparisons
Uses second-equivalents.

### Cross-system comparison (calendar vs UCUM)
The "above-week threshold" determines comparability:
- **Above-week**: year, years, month, months
- **At-or-below-week**: week, weeks, day, days, hour, hours, minute, minutes,
  second, seconds, millisecond, milliseconds

Rules:
- Calendar **above-week** vs UCUM → **incomparable** (returns `{}`)
- Calendar **at-or-below-week** vs UCUM time (`'s'`, `'min'`, `'h'`, `'d'`, `'wk'`, `'ms'`) →
  **comparable** via second-equivalents
- Calendar vs UCUM non-time (e.g., `'kg'`) → **incomparable** (returns `{}`)

### Incompatible UCUM dimensions
Returns `{}`.

## Output Format

- Quantity: `<value> <unit>` or `<value> '<unit>'`
- Boolean: `true` or `false`
- Empty/incomparable: `{}`
- Number: as string, trailing zeros stripped
