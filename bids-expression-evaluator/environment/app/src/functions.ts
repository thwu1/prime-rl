
export const builtinFunctions: Record<string, (...args: unknown[]) => unknown> = {
  index: (list: unknown, item: unknown): number | null => {
    if (!Array.isArray(list)) return null;
    const idx = list.indexOf(item);
    return idx !== -1 ? idx : null;
  },

  intersects: (a: unknown, b: unknown): unknown => {
    if (a === null || b === null) return false;
    const arrA = Array.isArray(a) ? a : [a];
    const arrB = Array.isArray(b) ? b : [b];
    const bSet = new Set(arrB);
    return arrA.filter((x: unknown) => bSet.has(x));
  },

  match: (target: unknown, regex: unknown): unknown => {
    if (typeof target !== 'string' || typeof regex !== 'string') return false;
    return new RegExp(regex).test(target);
  },

  type: (operand: unknown): string => {
    if (operand === null || operand === undefined) return 'null';
    if (Array.isArray(operand)) return 'array';
    return typeof operand;
  },

  min: (list: unknown): number | null => {
    if (list === null) return null;
    const arr = Array.isArray(list) ? list : [list];
    const nums = arr.map(Number).filter((x: number) => !isNaN(x));
    if (nums.length === 0) return null;
    return Math.min(...nums);
  },

  max: (list: unknown): number | null => {
    if (list === null) return null;
    const arr = Array.isArray(list) ? list : [list];
    const nums = arr.map(Number).filter((x: number) => !isNaN(x));
    if (nums.length === 0) return null;
    return Math.max(...nums);
  },

  length: (list: unknown): number | null => {
    if (Array.isArray(list) || typeof list === 'string') {
      return (list as string | unknown[]).length;
    }
    return null;
  },

  unique: (list: unknown): unknown[] | null => {
    if (list === null) return null;
    if (!Array.isArray(list)) return null;
    return [...new Set(list)];
  },

  count: (list: unknown, val: unknown): number => {
    if (!Array.isArray(list)) return 0;
    return list.filter((x: unknown) => x === val).length;
  },

  exists: (list: unknown, _rule: unknown): number => {
    if (list === null) return 0;
    if (!Array.isArray(list)) {
      list = [list];
    }
    return (list as unknown[]).filter((x: unknown) => x != null).length;
  },

  substr: (arg: unknown, start: unknown, end: unknown): string | null => {
    if (arg === null || start === null || end === null) return null;
    if (typeof arg !== 'string') return null;
    const s = start as number;
    const e = end as number;
    return arg.substr(s, e - s);
  },

  sorted: (list: unknown, method: unknown = 'auto'): unknown[] => {
    if (list === null) return [];
    if (!Array.isArray(list)) return [];
    const m = (method as string) || 'auto';
    const comparators: Record<string, (a: unknown, b: unknown) => number> = {
      numeric: (a: unknown, b: unknown) => Number(a) - Number(b),
      auto: (a: unknown, b: unknown) => {
        const sa = String(a), sb = String(b);
        if (sa < sb) return -1;
        if (sa > sb) return 1;
        return 0;
      },
      lexical: (a: unknown, b: unknown) => String(a).localeCompare(String(b)),
    };
    const cmp = comparators[m];
    if (!cmp) throw new Error(`Unknown sort method: ${m}`);
    return [...list].sort(cmp);
  },

  allequal: (a: unknown, b: unknown): boolean => {
    const arrA = a as unknown[];
    const arrB = b as unknown[];
    if (arrA.length !== arrB.length) return false;
    return arrA.every((v: unknown, i: number) => v === arrB[i]);
  },
};
