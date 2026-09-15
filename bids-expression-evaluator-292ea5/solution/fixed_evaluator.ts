import { Expr } from './types';

export type Context = Record<string, any>;

export function evaluate(expr: Expr, ctx: Context): any {
  switch (expr.kind) {
    case 'literal':
      return expr.value;

    case 'array':
      return expr.elements.map((e) => evaluate(e, ctx));

    case 'object':
      return {};

    case 'identifier': {
      const val = ctx[expr.name];
      return val === undefined ? null : val;
    }

    case 'unary':
      return evalUnary(expr.op, evaluate(expr.operand, ctx));

    case 'binary':
      return evalBinary(expr.op, expr.left, expr.right, ctx);

    case 'call':
      return evalCall(expr.name, expr.args.map((a) => evaluate(a, ctx)));

    case 'member': {
      const obj = evaluate(expr.object, ctx);
      if (obj === null || obj === undefined) return null;
      const val = obj[expr.property];
      return val === undefined ? null : val;
    }

    case 'index': {
      const obj = evaluate(expr.object, ctx);
      const idx = evaluate(expr.index, ctx);
      if (obj === null) return null;
      // FIX: support both arrays and strings for index access
      if (typeof obj === 'string') {
        return (obj as string)[idx as number] ?? null;
      }
      if (Array.isArray(obj)) {
        const val = obj[idx as number];
        return val === undefined ? null : val;
      }
      throw new Error(`Cannot index into ${typeof obj}`);
    }
  }
}

function evalUnary(op: string, val: any): any {
  switch (op) {
    case '!':
      return !val;
    case '-':
      if (val === null) return null;
      return -(val as number);
    default:
      throw new Error(`Unknown unary operator: ${op}`);
  }
}

function evalBinary(
  op: string,
  leftExpr: Expr,
  rightExpr: Expr,
  ctx: Context,
): any {
  // FIX: proper null-aware short-circuit for && and ||
  if (op === '&&') {
    const left = evaluate(leftExpr, ctx);
    if (left === false) return false;
    if (left === null) return null;
    return evaluate(rightExpr, ctx);
  }
  if (op === '||') {
    const left = evaluate(leftExpr, ctx);
    if (left === true) return true;
    return evaluate(rightExpr, ctx);
  }

  const left = evaluate(leftExpr, ctx);
  const right = evaluate(rightExpr, ctx);

  switch (op) {
    case '+':
      if (left === null || right === null) return null;
      return (left as any) + (right as any);
    case '-':
      if (left === null || right === null) return null;
      return (left as number) - (right as number);
    case '*':
      if (left === null || right === null) return null;
      return (left as number) * (right as number);
    case '/':
      if (left === null || right === null) return null;
      return (left as number) / (right as number);
    case '%':
      if (left === null || right === null) return null;
      return (left as number) % (right as number);
    case '==':
      return deepEqual(left, right);
    case '!=':
      return !deepEqual(left, right);
    case '<':
      if (left === null || right === null) return null;
      return left < right;
    case '<=':
      if (left === null || right === null) return null;
      return left <= right;
    case '>':
      if (left === null || right === null) return null;
      return left > right;
    case '>=':
      if (left === null || right === null) return null;
      return left >= right;
    case 'in': {
      // FIX: return null (not false) when RHS is null
      if (right === null) return null;
      if (left === null) return null;
      if (typeof right === 'object' && right !== null) {
        return (left as string) in right;
      }
      return false;
    }
    default:
      throw new Error(`Unknown binary operator: ${op}`);
  }
}

function deepEqual(a: any, b: any): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((v: any, i: number) => deepEqual(v, b[i]));
  }
  return false;
}

function evalCall(name: string, args: any[]): any {
  switch (name) {
    case 'match': {
      const [str, pattern] = args;
      if (str === null) return null;
      if (pattern === null) return false;
      return new RegExp(pattern as string).test(str as string);
    }

    case 'length': {
      const [val] = args;
      if (val === null) return null;
      return (val as any[]).length;
    }

    case 'type': {
      const [val] = args;
      if (val === null) return 'null';
      // FIX: check Array.isArray before typeof 'object'
      if (Array.isArray(val)) return 'array';
      if (typeof val === 'object') return 'object';
      return typeof val;
    }

    case 'intersects': {
      const [a, b] = args;
      if (a === null || b === null) return false;
      const result = (a as any[]).filter((x: any) =>
        (b as any[]).some((y: any) => deepEqual(x, y)),
      );
      // FIX: return false instead of empty array when no intersection
      if (result.length === 0) return false;
      return result;
    }

    case 'allequal': {
      const [a, b] = args;
      if (a === null || b === null) return false;
      if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) return false;
        return a.every((v: any, i: number) => deepEqual(v, b[i]));
      }
      return deepEqual(a, b);
    }

    case 'substr': {
      const [str, start, end] = args;
      if (str === null || start === null || end === null) return null;
      // FIX: third parameter is end index, not length
      return (str as string).substring(start as number, end as number);
    }

    case 'sorted': {
      const [arr, mode] = args;
      if (arr === null) return null;
      const copy = [...(arr as any[])];

      if (mode === 'lexical') {
        copy.sort((a: any, b: any) => String(a).localeCompare(String(b)));
      } else if (mode === 'numeric') {
        // FIX: handle "n/a" values — keep them in their original positions
        return sortNumericWithNa(copy);
      } else {
        // FIX: detect element type and use appropriate default sort
        const allNumbers = copy.length > 0 && copy.every((x: any) => typeof x === 'number');
        if (allNumbers) {
          copy.sort((a: number, b: number) => a - b);
        } else {
          copy.sort((a: any, b: any) => String(a).localeCompare(String(b)));
        }
      }
      return copy;
    }

    case 'min': {
      const [val] = args;
      if (val === null) return null;
      // FIX: handle scalar values
      if (typeof val === 'number') return val;
      // FIX: filter out "n/a" values
      const nums = (val as any[]).filter(
        (x: any) => typeof x === 'number' || (typeof x === 'string' && x !== 'n/a'),
      );
      if (nums.length === 0) return null;
      return Math.min(...nums.map(Number));
    }

    case 'max': {
      const [val] = args;
      if (val === null) return null;
      // FIX: handle scalar values
      if (typeof val === 'number') return val;
      // FIX: filter out "n/a" values
      const nums = (val as any[]).filter(
        (x: any) => typeof x === 'number' || (typeof x === 'string' && x !== 'n/a'),
      );
      if (nums.length === 0) return null;
      return Math.max(...nums.map(Number));
    }

    case 'unique': {
      const [arr] = args;
      if (arr === null) return null;
      const seen = new Set<any>();
      const result: any[] = [];
      for (const item of arr as any[]) {
        if (!seen.has(item)) {
          seen.add(item);
          result.push(item);
        }
      }
      return result;
    }

    case 'index': {
      const [arr, value] = args;
      if (arr === null) return null;
      const idx = (arr as any[]).findIndex((v: any) => deepEqual(v, value));
      return idx === -1 ? null : idx;
    }

    // FIX: implement count() function
    case 'count': {
      const [arr, value] = args;
      if (arr === null) return null;
      return (arr as any[]).filter((x: any) => deepEqual(x, value)).length;
    }

    case 'exists': {
      const [value, scheme] = args;
      if (value === null || scheme === null) return 0;
      return 0;
    }

    default:
      throw new Error(`Unknown function: ${name}`);
  }
}

// Helper: sort numerically while keeping "n/a" values in their original positions
function sortNumericWithNa(arr: any[]): any[] {
  const naIndices = new Set<number>();
  const nonNa: any[] = [];

  arr.forEach((val, idx) => {
    if (val === 'n/a') {
      naIndices.add(idx);
    } else {
      nonNa.push(val);
    }
  });

  nonNa.sort((a: any, b: any) => Number(a) - Number(b));

  const result: any[] = [];
  let ni = 0;
  for (let i = 0; i < arr.length; i++) {
    if (naIndices.has(i)) {
      result.push('n/a');
    } else {
      result.push(nonNa[ni++]);
    }
  }
  return result;
}
