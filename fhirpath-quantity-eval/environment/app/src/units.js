'use strict';

// Calendar duration units mapped to their second-equivalents
const calendarDuration2Seconds = {
  year: 31536000, years: 31536000,
  month: 2592000, months: 2592000,
  week: 604800, weeks: 604800,
  day: 86400, days: 86400,
  hour: 3600, hours: 3600,
  minute: 60, minutes: 60,
  second: 1, seconds: 1,
  millisecond: 0.001, milliseconds: 0.001
};

// Year-month conversion factors (1 year = 12 months)
const yearMonthFactor = {
  year: 12, years: 12,
  month: 1, months: 1
};

// Units considered "above the week threshold" for comparability rules.
// Calendar durations above this threshold cannot be compared with UCUM time units.
const aboveWeekUnits = new Set([
  'year', 'years', 'month', 'months',
  'week', 'weeks'
]);

// UCUM unit definitions: dimension and conversion factor to base SI unit
const ucumUnits = {
  kg:  { dimension: 'mass',   toBase: 1 },
  g:   { dimension: 'mass',   toBase: 0.001 },
  mg:  { dimension: 'mass',   toBase: 0.000001 },
  m:   { dimension: 'length', toBase: 1 },
  km:  { dimension: 'length', toBase: 1000 },
  cm:  { dimension: 'length', toBase: 0.01 },
  s:   { dimension: 'time',   toBase: 1 },
  min: { dimension: 'time',   toBase: 60 },
  h:   { dimension: 'time',   toBase: 3600 },
  '1': { dimension: 'dimensionless', toBase: 1 }
};

function isCalendarDuration(u) { return u in calendarDuration2Seconds; }
function isUcum(u) { return u in ucumUnits; }
function isAboveWeek(u) { return aboveWeekUnits.has(u); }

function singularUnit(u) {
  const map = {
    years:'year', months:'month', weeks:'week', days:'day',
    hours:'hour', minutes:'minute', seconds:'second', milliseconds:'millisecond'
  };
  return map[u] || u;
}

function pluralUnit(u) {
  const map = {
    year:'years', month:'months', week:'weeks', day:'days',
    hour:'hours', minute:'minutes', second:'seconds', millisecond:'milliseconds'
  };
  return map[u] || u;
}

/**
 * Determines the finer (smaller-granularity) of two calendar units.
 * Returns the singular form of the finer unit.
 */
function finerUnit(a, b) {
  const sa = calendarDuration2Seconds[a];
  const sb = calendarDuration2Seconds[b];
  if (sa == null || sb == null) return null;
  return sa <= sb ? singularUnit(a) : singularUnit(b);
}

/**
 * Convert a value from one UCUM unit to another compatible one.
 * Returns null if dimensions are incompatible.
 */
function convertUcum(value, fromUnit, toUnit) {
  const f = ucumUnits[fromUnit], t = ucumUnits[toUnit];
  if (!f || !t || f.dimension !== t.dimension) return null;
  return (value * f.toBase) / t.toBase;
}

module.exports = {
  calendarDuration2Seconds, yearMonthFactor, aboveWeekUnits, ucumUnits,
  isCalendarDuration, isUcum, isAboveWeek,
  singularUnit, pluralUnit, finerUnit, convertUcum
};
