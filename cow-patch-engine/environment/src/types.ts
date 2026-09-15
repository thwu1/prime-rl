
export interface Patch {
  op: "add" | "replace" | "remove";
  path: (string | number)[];
  value?: any;
}

export type Recipe<T> = (draft: T) => void | T | undefined;

export const DRAFT_STATE = Symbol.for("cow_draft_state");

export interface DraftState {
  type: "object" | "array";
  base: any;
  copy: any | null;
  modified: boolean;
  finalized: boolean;
  parent: DraftState | null;
  parentKey: string | number | null;
  assigned: Map<string | number, boolean>;
  draft: any;
  revoke: (() => void) | null;
}
