
import { readFileSync } from 'fs';
import yaml from 'js-yaml';
import { evaluateExpression } from './index';

export interface RuleSelector {
  suffixes?: string[];
  datatypes?: string[];
  extensions?: string[];
  entities?: Record<string, string>;
}

export interface RuleCheck {
  expression: string;
  level: 'error' | 'warning';
  reason: string;
  depends_on?: number;
}

export interface Rule {
  id: string;
  selectors: RuleSelector[];
  checks: RuleCheck[];
}

export interface FileContext {
  id: string;
  suffix: string;
  datatype: string;
  extension: string;
  entities: Record<string, string>;
  sidecar: Record<string, unknown>;
  columns: string[] | null;
}

export interface ValidationIssue {
  rule_id: string;
  check_index: number;
  level: 'error' | 'warning';
  reason: string;
  expression: string;
}

export interface ValidationReport {
  file_id: string;
  issues: ValidationIssue[];
  matched_rules: string[];
  passed: boolean;
}

export function loadRules(path: string): Rule[] {
  const raw = yaml.load(readFileSync(path, 'utf8')) as { rules: Rule[] };
  return raw.rules;
}

export function matchSelector(selector: RuleSelector, context: FileContext): boolean {
  if (selector.suffixes && selector.suffixes.length > 0) {
    if (!selector.suffixes.includes(context.suffix)) return false;
  }
  if (selector.datatypes && selector.datatypes.length > 0) {
    if (!selector.datatypes.includes(context.datatype)) return false;
  }
  if (selector.extensions && selector.extensions.length > 0) {
    if (!selector.extensions.includes(context.extension)) return false;
  }
  return true;
}

export function matchRule(rule: Rule, context: FileContext): boolean {
  return rule.selectors.some(sel => matchSelector(sel, context));
}

function buildEvalContext(fileContext: FileContext): Record<string, unknown> {
  return {
    suffix: fileContext.suffix,
    datatype: fileContext.datatype,
    extension: fileContext.extension,
    entities: fileContext.entities,
    ...fileContext.sidecar,
  };
}

export function evaluateRule(
  rule: Rule,
  fileContext: FileContext
): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const ctx = buildEvalContext(fileContext);
  const checkResults: boolean[] = [];

  for (let i = 0; i < rule.checks.length; i++) {
    const check = rule.checks[i];

    if (check.depends_on !== undefined && check.depends_on < checkResults.length) {
      if (checkResults[check.depends_on]) {
        checkResults.push(false);
        continue;
      }
    }

    let passed = false;
    try {
      const result = evaluateExpression(check.expression, ctx);
      passed = !!result;
    } catch {
      passed = false;
    }
    checkResults.push(passed);

    if (!passed) {
      issues.push({
        rule_id: rule.id,
        check_index: i,
        level: check.level,
        reason: check.reason,
        expression: check.expression,
      });
    }
  }

  return issues;
}

export function validate(
  rules: Rule[],
  context: FileContext
): ValidationReport {
  const matchedRules: string[] = [];
  const allIssues: ValidationIssue[] = [];

  for (const rule of rules) {
    if (matchRule(rule, context)) {
      matchedRules.push(rule.id);
      const issues = evaluateRule(rule, context);
      allIssues.push(...issues);
    }
  }

  const passed = allIssues.length === 0;

  return {
    file_id: context.id,
    issues: allIssues,
    matched_rules: matchedRules,
    passed,
  };
}

export function validateAll(
  rules: Rule[],
  contexts: FileContext[]
): ValidationReport[] {
  return contexts.map(ctx => validate(rules, ctx));
}
