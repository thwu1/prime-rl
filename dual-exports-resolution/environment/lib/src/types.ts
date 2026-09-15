import { Vector } from "./vector";

export interface VectorLike {
  readonly components: number[];
  readonly dimension: number;
}

export enum Dimension {
  TWO = 2,
  THREE = 3,
}

export function fromLike(like: VectorLike): Vector {
  return new Vector(like.components);
}
