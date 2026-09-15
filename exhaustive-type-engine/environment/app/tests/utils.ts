
export type Option<a> = { kind: 'none' } | { kind: 'some'; value: a };

export type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: string }
  | { status: 'error'; error: Error };

export type Event =
  | { type: 'fetch' }
  | { type: 'success'; data: string }
  | { type: 'error'; error: Error }
  | { type: 'cancel' };

export type BigUnion =
  | 'a' | 'b' | 'c' | 'd' | 'e' | 'f' | 'g' | 'h' | 'i'
  | 'j' | 'k' | 'l' | 'm' | 'n' | 'o' | 'p' | 'q' | 'r'
  | 's' | 't' | 'u' | 'v' | 'w' | 'x' | 'y' | 'z';
