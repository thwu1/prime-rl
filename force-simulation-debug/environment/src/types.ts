export interface SimNode {
  index: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx?: number | null;
  fy?: number | null;
}

export type RandomSource = () => number;

export interface Force {
  (alpha: number): void;
  initialize?: (nodes: SimNode[], random: RandomSource) => void;
}
