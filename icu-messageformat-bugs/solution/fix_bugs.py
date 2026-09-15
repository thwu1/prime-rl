#!/usr/bin/env python3

"""Fix all bugs in the ICU MessageFormat implementation and implement the
CLDR plural rule evaluator."""


def fix_parser():
    with open("/app/src/parser.ts", "r") as f:
        code = f.read()

    # Bug 1: selectordinal must use 'ordinal' pluralType, not 'cardinal'
    code = code.replace(
        "pluralType: 'cardinal',",
        "pluralType: argType === 'plural' ? 'cardinal' : 'ordinal',",
    )

    # Bug 2: offset value from parseDecimalInteger() is discarded — must store it
    code = code.replace(
        "this.parseDecimalInteger();\n        this.skipWhitespace();",
        "offset = this.parseDecimalInteger();\n        this.skipWhitespace();",
        1,  # only the first occurrence (inside the offset parsing block)
    )

    # Bug 3: double apostrophe '' should produce single apostrophe, not empty string
    code = code.replace(
        "this.pos += 2;\n      return '';",
        "this.pos += 2;\n      return \"'\";",
    )

    # Bug 4: apostrophe before '#' inside plural/selectordinal must start quoting
    code = code.replace(
        "const shouldQuote =\n"
        "      nextChar === '{' ||\n"
        "      nextChar === '}' ||\n"
        "      nextChar === '<' ||\n"
        "      nextChar === '>';",
        "const shouldQuote =\n"
        "      nextChar === '{' ||\n"
        "      nextChar === '}' ||\n"
        "      nextChar === '<' ||\n"
        "      nextChar === '>' ||\n"
        "      (nextChar === '#' &&\n"
        "        (parentArgType === 'plural' || parentArgType === 'selectordinal'));",
    )

    with open("/app/src/parser.ts", "w") as f:
        f.write(code)


def fix_formatter():
    with open("/app/src/formatter.ts", "r") as f:
        code = f.read()

    # Bug 5: # must use locale-aware number formatting, not String()
    code = code.replace(
        "result += String(currentPluralValue);",
        "result += new Intl.NumberFormat(locale).format(currentPluralValue);",
    )

    # Bug 6: plural category resolution must use (num - offset), not num
    code = code.replace(
        "const category = resolvePluralCategory(locale, num, el.pluralType);",
        "const category = resolvePluralCategory(locale, num - el.offset, el.pluralType);",
    )

    with open("/app/src/formatter.ts", "w") as f:
        f.write(code)


def implement_evaluator():

import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataDir = join(__dirname, '..', 'data');

type PluralCategory = 'zero' | 'one' | 'two' | 'few' | 'many' | 'other';

interface Operands {
  n: number;  // absolute value of the source number
  i: number;  // integer digits of n
  v: number;  // number of visible fraction digits (with trailing zeros)
  w: number;  // number of non-zero fraction digits
  f: number;  // visible fraction digits (as integer, with trailing zeros)
  t: number;  // visible fraction digits (as integer, without trailing zeros)
}

const cardinalData = JSON.parse(readFileSync(join(dataDir, 'plurals.json'), 'utf-8'));
const ordinalData = JSON.parse(readFileSync(join(dataDir, 'ordinals.json'), 'utf-8'));

const cardinalRules: Record<string, Record<string, string>> =
  cardinalData.supplemental['plurals-type-cardinal'];
const ordinalRules: Record<string, Record<string, string>> =
  ordinalData.supplemental['plurals-type-ordinal'];

function extractOperands(n: number): Operands {
  const abs = Math.abs(n);
  const str = String(abs);
  const dot = str.indexOf('.');
  if (dot === -1) {
    return { n: abs, i: abs, v: 0, w: 0, f: 0, t: 0 };
  }
  const intPart = parseInt(str.substring(0, dot), 10);
  const fracStr = str.substring(dot + 1);
  const trimmed = fracStr.replace(/0+$/, '');
  return {
    n: abs,
    i: intPart,
    v: fracStr.length,
    w: trimmed.length,
    f: parseInt(fracStr, 10) || 0,
    t: trimmed.length > 0 ? parseInt(trimmed, 10) : 0,
  };
}

function getOp(ops: Operands, name: string): number {
  switch (name) {
    case 'n': return ops.n;
    case 'i': return ops.i;
    case 'v': return ops.v;
    case 'w': return ops.w;
    case 'f': return ops.f;
    case 't': return ops.t;
    default: return 0;
  }
}

function parseValues(s: string): Array<number | [number, number]> {
  return s.split(',').map(p => {
    const t = p.trim();
    if (t.includes('..')) {
      const [a, b] = t.split('..').map(x => parseInt(x.trim(), 10));
      return [a, b] as [number, number];
    }
    return parseInt(t, 10);
  });
}

function inValues(val: number, list: Array<number | [number, number]>): boolean {
  for (const item of list) {
    if (typeof item === 'number') {
      if (val === item) return true;
    } else {
      if (val >= item[0] && val <= item[1]) return true;
    }
  }
  return false;
}

function evalRelation(ops: Operands, rel: string): boolean {
  const neg = rel.includes('!=');
  const [left, right] = rel.split(neg ? '!=' : '=').map(s => s.trim());
  let val: number;
  if (left.includes('%')) {
    const [opName, modStr] = left.split('%').map(s => s.trim());
    val = getOp(ops, opName) % parseInt(modStr, 10);
  } else {
    val = getOp(ops, left);
  }
  const matched = inValues(val, parseValues(right));
  return neg ? !matched : matched;
}

function evalRule(ops: Operands, rule: string): boolean {
  const at = rule.indexOf('@');
  const expr = (at !== -1 ? rule.substring(0, at) : rule).trim();
  if (!expr) return false;
  return expr.split(' or ').some(cond =>
    cond.trim().split(' and ').every(r => evalRelation(ops, r.trim()))
  );
}

function findRules(
  locale: string,
  type: 'cardinal' | 'ordinal'
): Record<string, string> | null {
  const data = type === 'cardinal' ? cardinalRules : ordinalRules;
  return data[locale] || data[locale.split('-')[0]] || null;
}

export function resolvePluralCategory(
  locale: string,
  value: number,
  type: 'cardinal' | 'ordinal'
): PluralCategory {
  const rules = findRules(locale, type);
  if (!rules) return value === 1 ? 'one' : 'other';
  const ops = extractOperands(value);
  for (const cat of ['zero', 'one', 'two', 'few', 'many'] as PluralCategory[]) {
    const rule = rules[`pluralRule-count-${cat}`];
    if (rule && evalRule(ops, rule)) return cat;
  }
  return 'other';
}
'''
    with open("/app/src/plural-rules.ts", "w") as f:
        f.write(code)


if __name__ == "__main__":
    fix_parser()
    fix_formatter()
    implement_evaluator()
    print("All bugs fixed and evaluator implemented.")
