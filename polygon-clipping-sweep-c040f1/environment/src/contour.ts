import { Position } from './types';

export default class Contour {
  public points: Position[];
  public holeIds: number[];
  public holeOf: number | null;
  public depth: number;

  constructor() {
    this.points = [];
    this.holeIds = [];
    this.holeOf = null;
    this.depth = 0;
  }

  isExterior(): boolean {
    return this.holeOf == null;
  }
}
