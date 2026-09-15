import { getPlatform } from "#platform";

export class Matrix {
  constructor(public readonly rows: number[][]) {}

  get size(): [number, number] {
    return [this.rows.length, this.rows[0]?.length ?? 0];
  }

  multiply(other: Matrix): Matrix {
    const [m, n] = this.size;
    const [, q] = other.size;
    if (n !== other.size[0]) throw new Error("Matrix dimension mismatch");
    const result: number[][] = [];
    for (let i = 0; i < m; i++) {
      result[i] = [];
      for (let j = 0; j < q; j++) {
        let sum = 0;
        for (let k = 0; k < n; k++) {
          sum += this.rows[i][k] * other.rows[k][j];
        }
        result[i][j] = sum;
      }
    }
    return new Matrix(result);
  }

  determinant(): number {
    const [m, n] = this.size;
    if (m !== n) throw new Error("Determinant requires square matrix");
    if (m === 1) return this.rows[0][0];
    if (m === 2) {
      return this.rows[0][0] * this.rows[1][1] - this.rows[0][1] * this.rows[1][0];
    }
    let det = 0;
    for (let j = 0; j < n; j++) {
      const minor = this.rows.slice(1).map(row => [
        ...row.slice(0, j),
        ...row.slice(j + 1),
      ]);
      det += (j % 2 === 0 ? 1 : -1) * this.rows[0][j] * new Matrix(minor).determinant();
    }
    return det;
  }

  transpose(): Matrix {
    const [m, n] = this.size;
    const result: number[][] = [];
    for (let i = 0; i < n; i++) {
      result[i] = [];
      for (let j = 0; j < m; j++) {
        result[i][j] = this.rows[j][i];
      }
    }
    return new Matrix(result);
  }
}

export function getPlatformId(): string {
  return getPlatform();
}
