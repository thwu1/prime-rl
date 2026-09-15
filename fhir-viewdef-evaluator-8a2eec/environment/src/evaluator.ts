import { evaluateFhirPath, processConstants } from './fhirpath-utils';
import { ViewDefinition, SelectExpression, Column, Row } from './types';

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
      if (expr.column && expr.column.length > 0) {
        const row: Row = {};
        for (const col of expr.column) {
          row[col.name] = null;
        }
        return [row];
      }
      return [];
    }
    const allRows: Row[] = [];
    for (const item of items) {
      const subRows = evaluateContent(expr, item, constants);
      allRows.push(...subRows);
    }
    return allRows;
  }

  if (expr.repeat && expr.repeat.length > 0) {
    const allItems: any[] = [];
    for (const p of expr.repeat) {
      const items = evaluateFhirPath(context, p, constants);
      allItems.push(...items);
    }
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
  const constants = processConstants(view.constant);

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
