#!/usr/bin/env python3
"""
Apply targeted fixes to the fhirpath-quantity evaluator.
Six bugs across three source files plus two missing implementations.
"""


def patch(path, old, new):
    with open(path) as f:
        content = f.read()
    if old not in content:
        raise ValueError(f"Patch target not found in {path}: {repr(old[:60])}")
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)


# --- Bug 1: Remove week/weeks from above-week threshold (src/units.js) ---
# The FHIRPath spec defines above-week as year(s) and month(s) only.
# Week-level durations are at the threshold, not above it, and should
# be comparable with UCUM time units.
patch('/app/src/units.js',
      "  'year', 'years', 'month', 'months',\n  'week', 'weeks'\n",
      "  'year', 'years', 'month', 'months'\n")


# --- Gap A: Add missing UCUM time units to the table (src/units.js) ---
# The spec lists 'd' (day), 'wk' (week), and 'ms' (millisecond) as
# supported UCUM time units but they are missing from the ucumUnits table.
patch('/app/src/units.js',
      "  '1': { dimension: 'dimensionless', toBase: 1 }",
      "  d:   { dimension: 'time',   toBase: 86400 },\n"
      "  wk:  { dimension: 'time',   toBase: 604800 },\n"
      "  ms:  { dimension: 'time',   toBase: 0.001 },\n"
      "  '1': { dimension: 'dimensionless', toBase: 1 }")


# --- Bug 2: Year+month addition must use 12-months factor (src/evaluator.js) ---
# When adding year-type and month-type calendar durations, the conversion
# must use 1 year = 12 months exactly, not the seconds-based approximation
# (which gives 31536000/2592000 = 12.1666... months per year).
patch('/app/src/evaluator.js',
      """  if (aIsCal && bIsCal) {
    const fine = units.finerUnit(a.unit, b.unit);""",
      """  if (aIsCal && bIsCal) {
    // Year/month special case: use exact 1 year = 12 months factor
    const factA = units.yearMonthFactor[a.unit];
    const factB = units.yearMonthFactor[b.unit];
    if (factA !== undefined && factB !== undefined &&
        units.singularUnit(a.unit) !== units.singularUnit(b.unit)) {
      const totalMonths = a.value * factA + b.value * factB;
      const ru = Math.abs(totalMonths) === 1 ? 'month' : 'months';
      return new Quantity(totalMonths, ru, false);
    }
    const fine = units.finerUnit(a.unit, b.unit);""")


# --- Bug 3: Compound unit separator should be '.' not '*' (src/evaluator.js) ---
# FHIRPath uses '.' as the compound unit separator for multiplication
# (e.g., 'kg.m'), not '*'.
patch('/app/src/evaluator.js',
      "    const compoundUnit = a.unit + '*' + b.unit;",
      "    const compoundUnit = a.unit + '.' + b.unit;")


# --- Bug 4: Implement calendar-to-UCUM time comparison (src/evaluator.js) ---
# Calendar durations at or below the week threshold can be compared with
# UCUM time units by converting both to seconds.
patch('/app/src/evaluator.js',
      """  // Calendar-to-UCUM time comparison requires further analysis
  return null;""",
      """  // Convert both to seconds and compare
  const calSec = calQ.value * units.calendarDuration2Seconds[calQ.unit];
  const ucumSec = ucumQ.value * ucumInfo.toBase;
  return aIsCal ? Math.sign(calSec - ucumSec) : Math.sign(ucumSec - calSec);""")


# --- Bug 5: UCUM unit regex must match digits (src/parser.js) ---
# The UCUM unit '1' (dimensionless) contains a digit. The tokenizer regex
# must allow alphanumeric characters in unit codes.
patch('/app/src/parser.js',
      """      i++; // skip opening quote
      let start = i;
      while (i < input.length && /[a-zA-Z]/.test(input[i])) i++;""",
      """      i++; // skip opening quote
      let start = i;
      while (i < input.length && /[a-zA-Z0-9]/.test(input[i])) i++;""")


# --- Bug 6: Number/quantity division must produce '1/unit' (src/evaluator.js) ---
# When dividing a number by a quantity, the result unit should be '1/<unit>'
# (e.g., '1/kg'), not '/<unit>'.
patch('/app/src/evaluator.js',
      "    const resultUnit = '/' + b.unit;",
      "    const resultUnit = '1/' + b.unit;")


# --- Gap B: Implement mixed calendar/UCUM time arithmetic (src/evaluator.js) ---
# Calendar durations at-or-below-week can be added/subtracted with UCUM time
# units. Convert both to seconds, compute the result, return in the left
# operand's unit system.
patch('/app/src/evaluator.js',
      "  // Mixed calendar and UCUM: incompatible for arithmetic\n  return EMPTY;",
      """  // Mixed calendar and UCUM time arithmetic
  const calQ = aIsCal ? a : b;
  const ucumQ = aIsCal ? b : a;

  // Calendar above-week: incompatible
  if (units.isAboveWeek(calQ.unit)) return EMPTY;

  // UCUM must be time dimension
  const ucumInfo = units.ucumUnits[ucumQ.unit];
  if (!ucumInfo || ucumInfo.dimension !== 'time') return EMPTY;

  // Convert both to seconds and add
  const calSec = calQ.value * units.calendarDuration2Seconds[calQ.unit];
  const ucumSec = ucumQ.value * ucumInfo.toBase;
  const totalSec = calSec + ucumSec;

  if (aIsCal) {
    // Result in left operand's calendar unit
    const secPerUnit = units.calendarDuration2Seconds[a.unit];
    const resultVal = totalSec / secPerUnit;
    const singUnit = units.singularUnit(a.unit);
    const resultUnit = Math.abs(resultVal) === 1 ? singUnit : units.pluralUnit(singUnit);
    return new Quantity(resultVal, resultUnit, false);
  } else {
    // Result in left operand's UCUM unit
    const resultVal = totalSec / units.ucumUnits[a.unit].toBase;
    return new Quantity(resultVal, a.unit, true);
  }""")


print("All 8 patches applied successfully.")
