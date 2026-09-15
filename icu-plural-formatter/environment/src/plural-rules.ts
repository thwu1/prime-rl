
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
 * Loads and evaluates CLDR plural rule expressions from the supplemental
 * JSON data files.
 */
export function resolvePlural(
  n: number,
  locale: string,
  type: 'cardinal' | 'ordinal',
): string {
  const base = locale.split('-')[0].toLowerCase();
  const data = type === 'cardinal' ? cardinalData : ordinalData;

  // Look up the locale's rule set from CLDR supplemental data
  const section = type === 'cardinal' ? 'plurals' : 'ordinals';
  const localeRules = data.supplemental[section]?.[base];

  if (!localeRules) return 'other';

  const absN = Math.abs(n);
  const i = Math.floor(absN);

  // Evaluate each plural category in CLDR priority order
  const cats: string[] = ['zero', 'one', 'two', 'few', 'many'];
  for (const cat of cats) {
    const ruleText = localeRules[`pluralRule-count-${cat}`];
    if (!ruleText) continue;

    // Strip @integer / @decimal sample list — only the condition matters
    const condition = ruleText.split('@')[0].trim();
    if (!condition) continue;

    if (evalCondition(condition, absN, i)) return cat;
  }

  return 'other';
}

// ---- CLDR plural rule expression evaluator ----

/**
 * Evaluate a CLDR plural rule condition against the given operand values.
 * Handles 'and' conjunction; each part must be a simple equality relation.
 */
function evalCondition(expr: string, n: number, i: number): boolean {
  const parts = expr.split(/\band\b/);
  for (const part of parts) {
    if (!evalRelation(part.trim(), n, i)) return false;
  }
  return true;
}

/**
 * Evaluate a single CLDR relation: operand = value[,value...]
 */
function evalRelation(rel: string, n: number, i: number): boolean {
  if (!rel) return true;

  const m = rel.match(/^([nivwft])\s*=\s*(\d+(?:\s*,\s*\d+)*)$/);
  if (!m) return false;

  const operand = m[1];
  const vals = m[2].split(',').map(v => parseInt(v.trim(), 10));

  let opVal: number;
  switch (operand) {
    case 'n': opVal = n; break;
    case 'i': opVal = i; break;
    default: opVal = 0;
  }

  return vals.includes(opVal);
}
