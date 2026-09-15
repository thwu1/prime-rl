export function untracked<T>(fn: () => T): T {
  return fn();
}
