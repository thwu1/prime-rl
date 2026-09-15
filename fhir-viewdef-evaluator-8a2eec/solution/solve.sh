#!/bin/bash

cd /app

# Install dependencies
npm install --loglevel=error 2>/dev/null

# Write the corrected evaluator
cat > /app/src/evaluator.ts << 'SOLVER_EOF'
import { evaluateFhirPath } from './fhirpath-utils';
import { ViewDefinition, SelectExpression, Column, Row } from './types';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { FP_DateTime, FP_Time } = require('fhirpath/src/types');

function crossProduct(rowsA: Row[], rowsB: Row[]): Row[] {
  if (rowsA.length === 0 || rowsB.length === 0) return [];
  const result: Row[] = [];
  for (const a of rowsA) {
    for (const b of rowsB) {
      result.push({ ...a, ...b });
    }
  }
  return result;
}

function collectColumnNames(expr: SelectExpression): string[] {
  const names: string[] = [];
  if (expr.column) {
    for (const col of expr.column) {
      names.push(col.name);
    }
  }
  if (expr.select) {
    for (const sub of expr.select) {
      names.push(...collectColumnNames(sub));
    }
  }
  if (expr.unionAll && expr.unionAll.length > 0) {
    names.push(...collectColumnNames(expr.unionAll[0]));
  }
  return names;
}

function makeNullRow(expr: SelectExpression): Row {
  const names = collectColumnNames(expr);
  const row: Row = {};
  for (const name of names) {
    row[name] = null;
  }
  return row;
}

function validateUnionColumns(branches: SelectExpression[]): void {
  if (branches.length < 2) return;
  const firstCols = collectColumnNames(branches[0]);
  for (let i = 1; i < branches.length; i++) {
    const branchCols = collectColumnNames(branches[i]);
    if (firstCols.length !== branchCols.length) {
      throw new Error(
        `unionAll branch ${i} has ${branchCols.length} columns, expected ${firstCols.length}`
      );
    }
    for (let j = 0; j < firstCols.length; j++) {
      if (firstCols[j] !== branchCols[j]) {
        throw new Error(
          `unionAll branch ${i} column ${j} is "${branchCols[j]}", expected "${firstCols[j]}"`
        );
      }
    }
  }
}

function wrapConstantValue(key: string, val: any): any {
  switch (key) {
    case 'valueDate':
    case 'valueDateTime':
    case 'valueInstant':
      return new FP_DateTime(val, val);
    case 'valueTime':
      return new FP_Time(val, val);
    default:
      return val;
  }
}

function validateAndProcessConstants(constants: any[] | undefined): Record<string, any> {
  if (!constants) return {};

  const result: Record<string, any> = {};
  for (const c of constants) {
    const name = c.name;
    let value: any = undefined;
    let found = false;
    let valueKey = '';

    for (const key of Object.keys(c)) {
      if (key.startsWith('value')) {
        value = c[key];
        valueKey = key;
        found = true;
        break;
      }
    }

    if (!found) {
      throw new Error(`Constant "${name}" has no value defined`);
    }

    result[name] = wrapConstantValue(valueKey, value);
  }

  return result;
}

function findConstantReferences(expr: string): string[] {
  const refs: string[] = [];
  const regex = /%([a-zA-Z_][a-zA-Z0-9_]*)/g;
  let match;
  while ((match = regex.exec(expr)) !== null) {
    refs.push(match[1]);
  }
  return refs;
}

function collectAllPaths(view: ViewDefinition): string[] {
  const paths: string[] = [];
  if (view.where) {
    for (const w of view.where) {
      paths.push(w.path);
    }
  }
  for (const sel of view.select) {
    collectPathsFromSelect(sel, paths);
  }
  return paths;
}

function collectPathsFromSelect(expr: SelectExpression, paths: string[]): void {
  if (expr.column) {
    for (const col of expr.column) {
      paths.push(col.path);
    }
  }
  if (expr.forEach) paths.push(expr.forEach);
  if (expr.forEachOrNull) paths.push(expr.forEachOrNull);
  if (expr.select) {
    for (const sub of expr.select) {
      collectPathsFromSelect(sub, paths);
    }
  }
  if (expr.unionAll) {
    for (const branch of expr.unionAll) {
      collectPathsFromSelect(branch, paths);
    }
  }
}

function validateConstantReferences(
  view: ViewDefinition,
  constants: Record<string, any>
): void {
  const builtins = new Set(['context', 'resource', 'rootResource', 'ucum']);
  const paths = collectAllPaths(view);
  for (const p of paths) {
    const refs = findConstantReferences(p);
    for (const ref of refs) {
      if (!builtins.has(ref) && !(ref in constants)) {
        throw new Error(`Undefined constant referenced: %${ref}`);
      }
    }
  }
}

function collectRepeatItems(
  context: any,
  paths: string[],
  constants: Record<string, any>
): any[] {
  const result: any[] = [];
  const queue: any[] = [context];

  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const p of paths) {
      const items = evaluateFhirPath(current, p, constants);
      for (const item of items) {
        result.push(item);
        queue.push(item);
      }
    }
  }

  return result;
}

function evaluateColumns(
  columns: Column[],
  context: any,
  constants: Record<string, any>
): Row {
  const row: Row = {};
  for (const col of columns) {
    const values = evaluateFhirPath(context, col.path, constants);
    if (col.collection === true) {
      row[col.name] = values;
    } else {
      if (values.length > 1) {
        throw new Error(
          `Column "${col.name}" produced ${values.length} values but collection is not true`
        );
      }
      row[col.name] = values.length > 0 ? values[0] : null;
    }
  }
  return row;
}

function evaluateSelectExpr(
  expr: SelectExpression,
  context: any,
  constants: Record<string, any>
): Row[] {
  if (expr.forEach) {
    const items = evaluateFhirPath(context, expr.forEach, constants);
    if (items.length === 0) return [];
    const allRows: Row[] = [];
    for (const item of items) {
      const subRows = evaluateContent(expr, item, constants);
      allRows.push(...subRows);
    }
    return allRows;
  }

  if (expr.forEachOrNull) {
    const items = evaluateFhirPath(context, expr.forEachOrNull, constants);
    if (items.length === 0) {
      return [makeNullRow(expr)];
    }
    const allRows: Row[] = [];
    for (const item of items) {
      const subRows = evaluateContent(expr, item, constants);
      allRows.push(...subRows);
    }
    return allRows;
  }

  if (expr.repeat && expr.repeat.length > 0) {
    const allItems = collectRepeatItems(context, expr.repeat, constants);
    if (allItems.length === 0) return [];
    const allRows: Row[] = [];
    for (const item of allItems) {
      const subRows = evaluateContent(expr, item, constants);
      allRows.push(...subRows);
    }
    return allRows;
  }

  return evaluateContent(expr, context, constants);
}

function evaluateContent(
  expr: SelectExpression,
  context: any,
  constants: Record<string, any>
): Row[] {
  const parts: Row[][] = [];

  if (expr.column && expr.column.length > 0) {
    const colRow = evaluateColumns(expr.column, context, constants);
    parts.push([colRow]);
  }

  if (expr.select && expr.select.length > 0) {
    for (const sub of expr.select) {
      const subRows = evaluateSelectExpr(sub, context, constants);
      parts.push(subRows);
    }
  }

  if (expr.unionAll && expr.unionAll.length > 0) {
    validateUnionColumns(expr.unionAll);
    const unionRows: Row[] = [];
    for (const branch of expr.unionAll) {
      const branchRows = evaluateSelectExpr(branch, context, constants);
      unionRows.push(...branchRows);
    }
    parts.push(unionRows);
  }

  if (parts.length === 0) return [{}];

  let result = parts[0];
  for (let i = 1; i < parts.length; i++) {
    result = crossProduct(result, parts[i]);
  }
  return result;
}

export function evaluate(view: ViewDefinition, resources: any[]): Row[] {
  if (!view.resource) {
    throw new Error('ViewDefinition must specify a resource type');
  }

  const constants = validateAndProcessConstants(view.constant);
  validateConstantReferences(view, constants);

  const matchingResources = resources.filter(
    (r) => r.resourceType === view.resource
  );

  const allRows: Row[] = [];

  for (const resource of matchingResources) {
    if (view.where && view.where.length > 0) {
      let passesWhere = true;
      for (const w of view.where) {
        const result = evaluateFhirPath(resource, w.path, constants);
        if (!result || result.length === 0 || result[0] !== true) {
          passesWhere = false;
          break;
        }
      }
      if (!passesWhere) continue;
    }

    let resourceRows: Row[] = [{}];
    for (const sel of view.select) {
      const selRows = evaluateSelectExpr(sel, resource, constants);
      resourceRows = crossProduct(resourceRows, selRows);
    }

    allRows.push(...resourceRows);
  }

  return allRows;
}
SOLVER_EOF

# Verify all tests pass
echo "Test data files found:"
ls -1 testdata/test_*.json 2>/dev/null
echo "---"

npx ts-node src/cli.ts run testdata/test_*.json
