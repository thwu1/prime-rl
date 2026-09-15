'use strict';

const units = require('./units');

class Quantity {
  constructor(value, unit, isUcum) {
    this.value = value;
    this.unit = unit;
    this.isUcum = isUcum;
  }
  toString() {
    const v = formatNumber(this.value);
    if (this.isUcum) return `${v} '${this.unit}'`;
    return `${v} ${this.unit}`;
  }
}

function formatNumber(n) {
  if (Number.isInteger(n)) return n.toString();
  return parseFloat(n.toPrecision(15)).toString();
}

const EMPTY = Symbol('EMPTY');

function evaluate(node) {
  switch (node.type) {
    case 'number':
      return node.value;
    case 'quantity':
      return new Quantity(node.value, node.unit, node.ucum);
    case 'negate': {
      const val = evaluate(node.operand);
      if (val === EMPTY) return EMPTY;
      if (val instanceof Quantity) return new Quantity(-val.value, val.unit, val.isUcum);
      return -val;
    }
    case 'binop':
      return evalBinop(node.op, evaluate(node.left), evaluate(node.right));
    default:
      throw new Error(`Unknown node type: ${node.type}`);
  }
}

function evalBinop(op, left, right) {
  if (left === EMPTY || right === EMPTY) return EMPTY;
  if (op === '+') return add(left, right);
  if (op === '-') return subtract(left, right);
  if (op === '*') return multiply(left, right);
  if (op === '/') return divide(left, right);
  if (['=', '!=', '<', '>', '<=', '>='].includes(op)) return compare(op, left, right);
  throw new Error(`Unknown operator: ${op}`);
}

// ─── Arithmetic ──────────────────────────────────────────────

function add(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a + b;
  if (a instanceof Quantity && b instanceof Quantity) return addQuantities(a, b);
  if (typeof a === 'number' && b instanceof Quantity)
    return addQuantities(new Quantity(a, '1', true), b);
  if (a instanceof Quantity && typeof b === 'number')
    return addQuantities(a, new Quantity(b, '1', true));
  return EMPTY;
}

function subtract(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (a instanceof Quantity && b instanceof Quantity)
    return addQuantities(a, new Quantity(-b.value, b.unit, b.isUcum));
  if (typeof a === 'number' && b instanceof Quantity)
    return addQuantities(new Quantity(a, '1', true), new Quantity(-b.value, b.unit, b.isUcum));
  if (a instanceof Quantity && typeof b === 'number')
    return addQuantities(a, new Quantity(-b, '1', true));
  return EMPTY;
}

function addQuantities(a, b) {
  const aIsCal = !a.isUcum && units.isCalendarDuration(a.unit);
  const bIsCal = !b.isUcum && units.isCalendarDuration(b.unit);

  // Both calendar durations
  if (aIsCal && bIsCal) {
    const fine = units.finerUnit(a.unit, b.unit);
    if (!fine) return EMPTY;
    const secsA = units.calendarDuration2Seconds[a.unit];
    const secsB = units.calendarDuration2Seconds[b.unit];
    const secsFine = units.calendarDuration2Seconds[fine];
    const result = (a.value * secsA + b.value * secsB) / secsFine;
    const resultUnit = Math.abs(result) === 1 ? fine : units.pluralUnit(fine);
    return new Quantity(result, resultUnit, false);
  }

  // Both UCUM
  if (a.isUcum && b.isUcum) {
    if (a.unit === b.unit) return new Quantity(a.value + b.value, a.unit, true);
    const converted = units.convertUcum(b.value, b.unit, a.unit);
    if (converted === null) return EMPTY;
    return new Quantity(a.value + converted, a.unit, true);
  }

  // Mixed calendar and UCUM: incompatible for arithmetic
  return EMPTY;
}

function multiply(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return a * b;
  if (a instanceof Quantity && typeof b === 'number')
    return new Quantity(a.value * b, a.unit, a.isUcum);
  if (typeof a === 'number' && b instanceof Quantity)
    return new Quantity(a * b.value, b.unit, b.isUcum);

  if (a instanceof Quantity && b instanceof Quantity) {
    const aIsCal = !a.isUcum && units.isCalendarDuration(a.unit);
    const bIsCal = !b.isUcum && units.isCalendarDuration(b.unit);
    if (aIsCal || bIsCal) return EMPTY;
    const compoundUnit = a.unit + '*' + b.unit;
    return new Quantity(a.value * b.value, compoundUnit, true);
  }
  return EMPTY;
}

function divide(a, b) {
  if (typeof b === 'number' && b === 0) return EMPTY;
  if (b instanceof Quantity && b.value === 0) return EMPTY;

  if (typeof a === 'number' && typeof b === 'number') return a / b;

  if (a instanceof Quantity && typeof b === 'number')
    return new Quantity(a.value / b, a.unit, a.isUcum);

  if (typeof a === 'number' && b instanceof Quantity) {
    if (!b.isUcum && units.isCalendarDuration(b.unit)) return EMPTY;
    const resultUnit = '/' + b.unit;
    return new Quantity(a / b.value, resultUnit, true);
  }

  if (a instanceof Quantity && b instanceof Quantity) {
    const aIsCal = !a.isUcum && units.isCalendarDuration(a.unit);
    const bIsCal = !b.isUcum && units.isCalendarDuration(b.unit);
    if (aIsCal || bIsCal) return EMPTY;

    if (a.unit === b.unit)
      return new Quantity(a.value / b.value, '1', true);

    const aInfo = units.ucumUnits[a.unit];
    const bInfo = units.ucumUnits[b.unit];
    if (aInfo && bInfo && aInfo.dimension === bInfo.dimension) {
      const converted = units.convertUcum(b.value, b.unit, a.unit);
      return new Quantity(a.value / converted, '1', true);
    }

    const compoundUnit = a.unit + '/' + b.unit;
    return new Quantity(a.value / b.value, compoundUnit, true);
  }
  return EMPTY;
}

// ─── Comparison ──────────────────────────────────────────────

function compare(op, a, b) {
  const cmp = compareValues(a, b);
  if (cmp === null) return EMPTY;
  switch (op) {
    case '=':  return cmp === 0;
    case '!=': return cmp !== 0;
    case '<':  return cmp < 0;
    case '>':  return cmp > 0;
    case '<=': return cmp <= 0;
    case '>=': return cmp >= 0;
  }
}

function compareValues(a, b) {
  if (typeof a === 'number' && typeof b === 'number') return Math.sign(a - b);
  if (a instanceof Quantity && b instanceof Quantity) return compareQuantities(a, b);
  if (typeof a === 'number' && b instanceof Quantity)
    return compareQuantities(new Quantity(a, '1', true), b);
  if (a instanceof Quantity && typeof b === 'number')
    return compareQuantities(a, new Quantity(b, '1', true));
  return null;
}

function compareQuantities(a, b) {
  const aIsCal = !a.isUcum && units.isCalendarDuration(a.unit);
  const bIsCal = !b.isUcum && units.isCalendarDuration(b.unit);

  if (aIsCal && bIsCal) return compareCalendarDurations(a, b);
  if (a.isUcum && b.isUcum) return compareUcumQuantities(a, b);
  if ((aIsCal && b.isUcum) || (a.isUcum && bIsCal))
    return compareMixedDurations(a, b, aIsCal, bIsCal);
  return null;
}

function compareCalendarDurations(a, b) {
  if (units.singularUnit(a.unit) === units.singularUnit(b.unit))
    return Math.sign(a.value - b.value);
  const factA = units.yearMonthFactor[a.unit];
  const factB = units.yearMonthFactor[b.unit];
  if (factA && factB) return Math.sign(a.value * factA - b.value * factB);
  const secsA = units.calendarDuration2Seconds[a.unit];
  const secsB = units.calendarDuration2Seconds[b.unit];
  return Math.sign(a.value * secsA - b.value * secsB);
}

function compareUcumQuantities(a, b) {
  if (a.unit === b.unit) return Math.sign(a.value - b.value);
  const converted = units.convertUcum(b.value, b.unit, a.unit);
  if (converted === null) return null;
  return Math.sign(a.value - converted);
}

function compareMixedDurations(a, b, aIsCal, bIsCal) {
  const calQ = aIsCal ? a : b;
  const ucumQ = aIsCal ? b : a;

  // Calendar durations above the week threshold are incomparable with UCUM
  if (units.isAboveWeek(calQ.unit)) return null;

  // Non-time UCUM units are incomparable with calendar durations
  const ucumInfo = units.ucumUnits[ucumQ.unit];
  if (!ucumInfo || ucumInfo.dimension !== 'time') return null;

  // Calendar-to-UCUM time comparison requires further analysis
  return null;
}

// ─── Formatting ──────────────────────────────────────────────

function formatResult(val) {
  if (val === EMPTY) return '{}';
  if (typeof val === 'boolean') return val.toString();
  if (typeof val === 'number') return formatNumber(val);
  if (val instanceof Quantity) return val.toString();
  return '{}';
}

module.exports = { evaluate, formatResult, Quantity, EMPTY };
