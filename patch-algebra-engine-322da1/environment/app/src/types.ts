export interface ImmerPatch {
  op: "add" | "remove" | "replace";
  path: PathSegment[];
  value?: any;
}

export interface RFC6902Patch {
  op: "add" | "remove" | "replace" | "test" | "move" | "copy";
  path: string;
  value?: any;
  from?: string;
}

export interface PatchConflict {
  type: "write-write" | "write-delete" | "delete-write";
  pathA: PathSegment[];
  pathB: PathSegment[];
  patchIndexA: number;
  patchIndexB: number;
}

export type PathSegment = string | number;
