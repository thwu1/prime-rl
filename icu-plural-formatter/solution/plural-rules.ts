
import * as fs from 'fs';
import * as path from 'path';

interface CLDRPluralData {
  supplemental: Record<string, Record<string, Record<string, string>>>;
}

// Load CLDR supplemental plural rule data at module initialization
const cardinalData: CLDRPluralData = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '..', 'data', 'supplemental', 'plurals.json'),
    'utf-8',
  ),
);
const ordinalData: CLDRPluralData = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, '..', 'data', 'supplemental', 'ordinals.json'),
    'utf-8',
  ),
);

/**
 * Resolve the CLDR plural category for a given number and locale.
 *
 * Parses and evaluates CLDR plural rule expressions loaded from the
 * supplemental JSON data files. Supports all locales present in the data
 * for both cardinal and ordinal plural types.
 */
export function resolvePlural(
  n: number,
  locale: string,
  type: 'cardinal' | 'ordinal',
): string {
  const base = locale.split('-')[0].toLowerCase();
  const data = type === 'cardinal' ? cardinalData : ordinalData;

  // Look up the locale's rule set from CLDR supplemental data
  const section = type === 'cardinal'
    ? 'plurals-type-cardinal'
    : 'plurals-type-ordinal';
  const localeRules = data.supplemental[section]?.[base];

  if (!localeRules) return 'other';

  // Compute CLDR operands (for integer values: v=w=f=t=0)
  const absN = Math.abs(n);
  const i = Math.floor(absN);
  const operands: Operands = { n: absN, i, v: 0, w: 0, f: 0, t: 0 };

  // Evaluate each plural category in CLDR priority order
  const cats: string[] = ['zero', 'one', 'two', 'few', 'many'];
  for (const cat of cats) {
    const ruleText = localeRules[`pluralRule-count-${cat}`];
    if (!ruleText) continue;

    // Strip @integer / @decimal sample list — only the condition matters
    const condition = ruleText.split('@')[0].trim();
    if (!condition) continue;

    if (evalCondition(condition, operands)) return cat;
  }

  return 'other';
}

// ---- CLDR plural rule expression evaluator ----

interface Operands {
  n: number;
  i: number;
  v: number;
  w: number;
  f: number;
  t: number;
}

/** Top-level evaluation: disjunction of and-conditions separated by 'or'. */
function evalCondition(expr: string, ops: Operands): boolean {
  const orParts = expr.split(/\bor\b/);
  for (const part of orParts) {
    if (evalAndCondition(part.trim(), ops)) return true;
  }
  return false;
}

/** Conjunction of relations separated by 'and'. */
function evalAndCondition(expr: string, ops: Operands): boolean {
  const andParts = expr.split(/\band\b/);
  for (const part of andParts) {
    if (!evalRelation(part.trim(), ops)) return false;
  }
  return true;
}

/**
 * Evaluate a single CLDR relation:
 *   operand [% modulus] (= | !=) range_list
 */
function evalRelation(rel: string, ops: Operands): boolean {
  if (!rel) return true;

  const m = rel.match(
    /^([nivwft])\s*(?:%\s*(\d+))?\s*(!=|=)\s*(.+)$/,
  );
  if (!m) return false;

  const opName = m[1] as keyof Operands;
  const mod = m[2] ? parseInt(m[2], 10) : null;
  const operator = m[3]; // '=' or '!='
  const rangeListStr = m[4];

  let val = ops[opName];
  if (mod !== null) val = val % mod;

  const matches = evalRangeList(val, rangeListStr);
  return operator === '!=' ? !matches : matches;
}

/**
 * Check if val falls within any item in a comma-separated range list.
 * Items can be single values (e.g. "1") or inclusive ranges (e.g. "3..10").
 */
function evalRangeList(val: number, rangeList: string): boolean {
  const parts = rangeList.split(',');
  for (const part of parts) {
    const trimmed = part.trim();
    const dotDot = trimmed.indexOf('..');
    if (dotDot !== -1) {
      const lo = parseInt(trimmed.substring(0, dotDot), 10);
      const hi = parseInt(trimmed.substring(dotDot + 2), 10);
      if (val >= lo && val <= hi) return true;
    } else {
      const exact = parseInt(trimmed, 10);
      if (!isNaN(exact) && val === exact) return true;
    }
  }
  return false;
}
