function valuesOfObj<T>(record: Record<string, T>): T[] {
  if ('values' in Object) {
    return Object.values(record);
  }
  const values: T[] = [];
  for (const key in record) {
    if (record.hasOwnProperty(key)) {
      values.push(record[key]);
    }
  }
  return values;
}

export function find<T>(
  record: Record<string, T>,
  predicate: (v: T) => boolean
): T | undefined {
  const values = valuesOfObj(record);
  if ('find' in values) {
    return values.find(predicate);
  }
  const valuesNotNever = values as T[];
  for (let i = 0; i < valuesNotNever.length; i++) {
    const value = valuesNotNever[i];
    if (predicate(value)) {
      return value;
    }
  }
  return undefined;
}

export function forEach<T>(
  record: Record<string, T>,
  run: (v: T, key: string) => void
) {
  Object.entries(record).forEach(([key, value]) => {
    if (value !== undefined) run(value, key);
  });
}

export function includes<T>(arr: T[], value: T) {
  return arr.indexOf(value) !== -1;
}

export function findArr<T>(
  record: T[],
  predicate: (v: T) => boolean
): T | undefined {
  for (let i = 0; i < record.length; i++) {
    const value = record[i];
    if (predicate(value)) {
      return value;
    }
  }
  return undefined;
}
