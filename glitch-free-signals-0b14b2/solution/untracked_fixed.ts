import { setActiveConsumer } from './graph';

export function untracked<T>(fn: () => T): T {
  const prev = setActiveConsumer(null);
  try {
    return fn();
  } finally {
    setActiveConsumer(prev);
  }
}
