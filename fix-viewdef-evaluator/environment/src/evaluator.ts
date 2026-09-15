
// SQL-on-FHIR v2 ViewDefinition Evaluator
// Transforms FHIR resources into flat tabular rows per a ViewDefinition spec.

import { fhirpathEvaluate } from './fhirpath-helper';
import { validate } from './validate';
import type { Row, EnvVars } from './types';

function assert(condition: any, message?: string | Error): asserts condition {
  if (!condition) {
    throw typeof message === 'string' ? new Error(message) : (message || new Error('Assertion failed'));
  }
}

function merge(a: Row, b: Row): Row {
  return Object.assign({}, a, b);
}

function rowProduct(parts: Row[][]): Row[] {
  if (parts.length === 1) {
    return parts[0];
  }
  let rows: Row[] = [{}];
  parts.forEach((partialRows) => {
    const newRows: Row[] = [];
    partialRows.forEach((partialRow) => {
      rows.forEach((row) => {
        newRows.push(merge(partialRow, row));
      });
    });
    rows = newRows;
  });
  return rows;
}

function handleForEach(selectExpr: any, node: any, def: any, envVars: EnvVars = {}): Row[] {
  assert(selectExpr.forEach, 'forEach required');
  const nodes = fhirpathEvaluate(node, selectExpr.forEach, def.constant, envVars);
  return nodes.flatMap((n: any, index: number) => {
    const childEnvVars = { ...envVars, rowIndex: index };
    return handleSelect({ select: selectExpr.select }, n, def, childEnvVars);
  });
}

function handleForEachOrNull(selectExpr: any, node: any, def: any, envVars: EnvVars = {}): Row[] {
  assert(selectExpr.forEachOrNull, 'forEachOrNull required');
  let nodes = fhirpathEvaluate(node, selectExpr.forEachOrNull, def.constant, envVars);
  return nodes.flatMap((n: any, index: number) => {
    const childEnvVars = { ...envVars, rowIndex: index };
    return handleSelect({ select: selectExpr.select }, n, def, childEnvVars);
  });
}

function recursiveTraverse(paths: string[], node: any, def: any, envVars: EnvVars = {}): any[] {
  const result: any[] = [];

  const traverse = (currentNode: any, isRoot: boolean = false) => {
    result.push(currentNode);

    paths.forEach((p: string) => {
      const childNodes = fhirpathEvaluate(currentNode, p, def.constant, envVars);
      childNodes.forEach((childNode: any) => {
        if (childNode && typeof childNode === 'object') {
          traverse(childNode, false);
        }
      });
    });
  };

  traverse(node, true);
  return result;
}

function handleRepeat(selectExpr: any, node: any, def: any, envVars: EnvVars = {}): Row[] {
  assert(selectExpr.repeat, 'repeat required');
  assert(Array.isArray(selectExpr.repeat), 'repeat must be an array');

  const nodes = recursiveTraverse(selectExpr.repeat, node, def, envVars);

  return nodes.flatMap((n: any) => {
    return handleSelect({ select: selectExpr.select }, n, def, envVars);
  });
}

function handleColumn(selectExpr: any, node: any, def: any, envVars: EnvVars = {}): Row[] {
  assert(selectExpr.column, 'column required');
  const record: Row = {};
  selectExpr.column.forEach((c: any) => {
    const vs = fhirpathEvaluate(node, c.path, def.constant, envVars);
    if (vs.length <= 1) {
      const v = vs[0];
      record[c.name || c.path] = v === undefined ? null : v;
    } else {
      throw new Error('Collection value for ' + c.path + ' => ' + JSON.stringify(vs));
    }
  });
  return [record];
}

function arraysEq(a: any[], b: any[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; ++i) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function arraysUnique(arrays: any[][]): any[][] {
  return arrays.reduce((acc: any[][], value: any[]) => {
    if (acc.length === 0) return [value];
    for (const x of acc) {
      if (arraysEq(x, value)) return acc;
    }
    return acc.concat([value]);
  }, []);
}

function handleUnionAll(selectExpr: any, node: any, def: any, envVars: EnvVars = {}): Row[] {
  assert(selectExpr.unionAll, 'unionAll');
  const result = selectExpr.unionAll.flatMap((d: any) => doEval(d, node, def, envVars));
  const unique = arraysUnique(result.map((x: Row) => Object.keys(x)));
  assert(unique.length <= 1, new Error(`Union columns mismatch: ${JSON.stringify(unique)}`));
  return result;
}

function handleSelect(selectExpr: any, node: any, def: any, envVars: EnvVars = {}): Row[] {
  assert(selectExpr.select, 'select');
  if (selectExpr.where) {
    const include = selectExpr.where.every((w: any) => {
      const val = fhirpathEvaluate(node, w.path, def.constant, envVars)[0];
      assert(
        val === undefined || typeof val === 'boolean',
        "'where' expression path should return 'boolean'"
      );
      return val;
    });
    if (!include) {
      return [];
    }
  }
  if (selectExpr.resource) {
    if (selectExpr.resource !== node.resourceType) {
      return [];
    }
  }
  return rowProduct(
    selectExpr.select.map((s: any) => doEval(s, node, def, envVars))
  );
}

function normalize(def: any): any {
  if (def.forEach) {
    def.select = def.select || [];
    def.type = 'forEach';
    if (def.unionAll) {
      def.select.unshift({ unionAll: def.unionAll });
      delete def.unionAll;
    }
    if (def.column) {
      def.select.unshift({ column: def.column });
      delete def.column;
    }
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else if (def.forEachOrNull) {
    def.select = def.select || [];
    def.type = 'forEachOrNull';
    if (def.unionAll) {
      def.select.unshift({ unionAll: def.unionAll });
      delete def.unionAll;
    }
    if (def.column) {
      def.select.unshift({ column: def.column });
      delete def.column;
    }
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else if (def.repeat) {
    def.select = def.select || [];
    def.type = 'repeat';
    if (def.unionAll) {
      def.select.unshift({ unionAll: def.unionAll });
      delete def.unionAll;
    }
    if (def.column) {
      def.select.unshift({ column: def.column });
      delete def.column;
    }
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else if (def.column && def.select && def.unionAll) {
    def.type = 'select';
    def.select.unshift({ column: def.column });
    def.select.unshift({ unionAll: def.unionAll });
    delete def.column;
    delete def.unionAll;
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else if (def.unionAll && def.select) {
    def.type = 'select';
    def.select.unshift({ unionAll: def.unionAll });
    delete def.unionAll;
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else if (def.select && def.column) {
    def.select.unshift({ column: def.column });
    delete def.column;
    def.type = 'select';
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else if (def.unionAll && def.column) {
    def.select = def.select || [];
    def.select.unshift({ unionAll: def.unionAll });
    def.select.unshift({ column: def.column });
    delete def.unionAll;
    delete def.column;
    def.type = 'select';
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else if (def.select) {
    def.type = 'select';
    def.select = def.select.map((s: any) => normalize(s));
    return def;
  } else {
    if (def.unionAll) {
      def.type = 'unionAll';
      def.unionAll = def.unionAll.map((s: any) => normalize(s));
    } else if (def.column) {
      def.type = 'column';
    } else if (def.forEach) {
      def.type = 'forEach';
    } else if (def.forEachOrNull) {
      def.type = 'forEachOrNull';
    } else if (def.repeat) {
      def.type = 'repeat';
    } else if (def.select) {
      def.type = 'select';
    }
    return def;
  }
}

const fns: Record<string, Function> = {
  forEach: handleForEach,
  forEachOrNull: handleForEachOrNull,
  repeat: handleRepeat,
  unionAll: handleUnionAll,
  select: handleSelect,
  column: handleColumn,
  unknown: () => [],
};

function doEval(selectExpr: any, node: any, def: any, envVars: EnvVars = {}): Row[] {
  const f = fns[selectExpr.type] || fns['unknown'];
  return f(selectExpr, node, def, envVars);
}

function collectColumns(acc: string[], def: any): string[] {
  switch (def.type) {
    case 'select':
    case 'forEach':
    case 'forEachOrNull':
    case 'repeat':
      return def.select.reduce((a: string[], s: any) => collectColumns(a, s), acc);
    case 'unionAll': {
      const unions = def.unionAll.map((s: any) => collectColumns([], s));
      if (unions.length > 1) {
        const first = unions[0];
        for (let i = 1; i < unions.length; ++i) {
          if (!arraysEq(first, unions[i])) {
            throw new Error(`Union columns mismatch: ${JSON.stringify(unions)}`);
          }
        }
      }
      return acc.concat(unions[0]);
    }
    case 'column':
      return def.column.reduce((a: string[], c: any) => {
        a.push(c.name || c.path);
        return a;
      }, acc);
    default:
      return acc;
  }
}

export function getColumns(def: any): string[] {
  return collectColumns([], normalize(structuredClone(def)));
}

export function evaluate(def: any, node: any, forTest: boolean = true): Row[] {
  if (!Array.isArray(node)) {
    return evaluate(def, [node], forTest);
  }

  const validation = validate(def, forTest);
  if ((validation.errors || []).length > 0) {
    throw new Error(
      'Incorrect view definition:\n' + JSON.stringify(validation.errors, null, 2)
    );
  }

  const normalDef = normalize(structuredClone(def));
  const initialEnvVars: EnvVars = { rowIndex: 0 };
  return node.flatMap((n: any) => doEval(normalDef, n, def, initialEnvVars));
}
