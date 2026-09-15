#!/usr/bin/env python3
"""
Diagnose and repair TypeScript module resolution configuration, source code
defects, and missing implementations in @mathkit/linalg and its consumer.

Instead of fragile string-replacement patching, this script writes complete
corrected file contents for each broken file to guarantee correctness.

"""

import json
import os
import sys


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def write_text(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


# ── Fix 1-4: Library package.json exports and imports maps ───────────────────

def fix_lib_package_json():
    path = "/app/lib/package.json"
    pkg = read_json(path)

    # Bug 1: Root export "import" default uses .mjs but type:module emits .js
    # Bug 2: Export key "./vector.js" should be "./vector"
    # Bug 3: ./types export references "typedefs" but source is types.ts
    pkg["exports"] = {
        ".": {
            "import": {
                "types": "./dist/index.d.ts",
                "default": "./dist/index.js"
            },
            "default": "./dist/index.js"
        },
        "./vector": {
            "types": "./dist/vector.d.ts",
            "default": "./dist/vector.js"
        },
        "./matrix": {
            "types": "./dist/matrix.d.ts",
            "default": "./dist/matrix.js"
        },
        "./types": {
            "types": "./dist/types.d.ts",
            "default": "./dist/types.js"
        },
        "./plugins/*": {
            "types": "./dist/plugins/*.d.ts",
            "default": "./dist/plugins/*.js"
        }
    }

    # Bug 4: #platform imports reference source paths with wrong filenames
    pkg["imports"] = {
        "#platform": {
            "node": "./dist/platform/node.js",
            "default": "./dist/platform/fallback.js"
        }
    }

    write_json(path, pkg)
    print("Fixed: /app/lib/package.json")
    print("  - Bug 1: .mjs -> .js in root export")
    print("  - Bug 2: ./vector.js -> ./vector export key")
    print("  - Bug 3: typedefs -> types in ./types export")
    print("  - Bug 4: #platform imports -> dist/ paths")


# ── Fix 5: Library tsconfig.json ─────────────────────────────────────────────

def fix_lib_tsconfig():
    path = "/app/lib/tsconfig.json"
    config = read_json(path)
    # Bug 5: declaration:false prevents .d.ts generation
    config["compilerOptions"]["declaration"] = True
    write_json(path, config)
    print("Fixed: /app/lib/tsconfig.json")
    print("  - Bug 5: declaration: true")


# ── Fix 6-7: Consumer tsconfig.json ──────────────────────────────────────────

def fix_consumer_tsconfig():
    path = "/app/consumer/tsconfig.json"
    config = read_json(path)
    # Bug 6: module:"esnext" -> "nodenext"
    # Bug 7: moduleResolution:"bundler" -> "nodenext"
    config["compilerOptions"]["module"] = "nodenext"
    config["compilerOptions"]["moduleResolution"] = "nodenext"
    write_json(path, config)
    print("Fixed: /app/consumer/tsconfig.json")
    print("  - Bug 6: module -> nodenext")
    print("  - Bug 7: moduleResolution -> nodenext")


# ── Fix 8: types.ts import extension ─────────────────────────────────────────

def fix_types_ts():
    # Bug 8: import from "./vector" missing .js extension for nodenext ESM
    write_text("/app/lib/src/types.ts", '''\
import { Vector } from "./vector.js";

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
''')
    print("Fixed: /app/lib/src/types.ts")
    print('  - Bug 8: "./vector" -> "./vector.js"')


# ── Fix 9: index.ts type re-export ───────────────────────────────────────────

def fix_index_ts():
    # Bug 9: Under isolatedModules:true, re-exporting VectorLike (an interface)
    # without the 'type' keyword causes TS1205
    write_text("/app/lib/src/index.ts", '''\
export { Vector } from "@mathkit/linalg/vector";
export { Matrix, getPlatformId } from "./matrix.js";
export { Dimension, fromLike } from "./types.js";
export type { VectorLike } from "./types.js";
''')
    print("Fixed: /app/lib/src/index.ts")
    print("  - Bug 9: export type { VectorLike }")


# ── Fix 10: consumer main.ts import extension ────────────────────────────────

def fix_consumer_main():
    # Bug 10: import from "./helpers" missing .js extension
    write_text("/app/consumer/src/main.ts", '''\
import { Vector, Matrix, getPlatformId, Dimension } from "@mathkit/linalg";
import { fromLike, type VectorLike } from "@mathkit/linalg/types";
import { Matrix as MatrixDirect } from "@mathkit/linalg/matrix";
import { rotate2D } from "@mathkit/linalg/plugins/transform";
import { lerp } from "@mathkit/linalg/plugins/interpolate";
import { mean, covarianceMatrix } from "@mathkit/linalg/plugins/statistics";
import { formatVector } from "./helpers.js";

const v1 = new Vector([1, 0, 0]);
const v2 = new Vector([0, 1, 0]);
const cross = v1.cross(v2);
console.log("cross:", formatVector(cross));

const m = new MatrixDirect([[1, 2], [3, 4]]);
console.log("det:", m.determinant());
console.log("trace:", m.trace());

const dim = Dimension.THREE;
console.log("dim:", dim);

const coords: VectorLike = { components: [1, 2, 3], dimension: dim };
const v3 = fromLike(coords);
console.log("from-interface:", formatVector(v3));

const rotated = rotate2D(new Vector([1, 0]), Math.PI / 2);
console.log("rotated:", formatVector(rotated));

const a = new Vector([0, 0]);
const b = new Vector([10, 10]);
const mid = lerp(a, b, 0.5);
console.log("lerp:", formatVector(mid));

const dataset = [new Vector([1, 2]), new Vector([3, 4]), new Vector([5, 6])];
const avg = mean(dataset);
console.log("mean:", formatVector(avg));

const cov = covarianceMatrix(dataset);
console.log("cov-trace:", cov.trace());

console.log("platform:", getPlatformId());
''')
    print("Fixed: /app/consumer/src/main.ts")
    print('  - Bug 10: "./helpers" -> "./helpers.js"')


# ── Fix 11: Matrix.trace() method ────────────────────────────────────────────

def fix_matrix_ts():
    # Bug 11: Matrix class is missing trace() method.
    # Write the complete corrected file to avoid fragile string replacement.
    write_text("/app/lib/src/matrix.ts", '''\
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

  trace(): number {
    const [m, n] = this.size;
    if (m !== n) throw new Error("Trace requires square matrix");
    let sum = 0;
    for (let i = 0; i < m; i++) {
      sum += this.rows[i][i];
    }
    return sum;
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
''')
    print("Fixed: /app/lib/src/matrix.ts")
    print("  - Bug 11: added trace() method")


# ── Fix 12: Create statistics plugin ─────────────────────────────────────────

def create_statistics_module():
    # Bug 12: plugins/statistics.ts doesn't exist. Create with mean() and
    # covarianceMatrix() using correct nodenext imports and sample covariance.
    write_text("/app/lib/src/plugins/statistics.ts", '''\
import { Vector } from "../vector.js";
import { Matrix } from "../matrix.js";

export function mean(vectors: Vector[]): Vector {
  if (vectors.length === 0) throw new Error("Cannot compute mean of empty array");
  const dim = vectors[0].dimension;
  const sums = new Array(dim).fill(0);
  for (const v of vectors) {
    if (v.dimension !== dim) throw new Error("All vectors must have same dimension");
    for (let i = 0; i < dim; i++) {
      sums[i] += v.components[i];
    }
  }
  return new Vector(sums.map(s => s / vectors.length));
}

export function covarianceMatrix(vectors: Vector[]): Matrix {
  if (vectors.length < 2) throw new Error("Need at least 2 vectors for covariance");
  const dim = vectors[0].dimension;
  const m = mean(vectors);
  const rows: number[][] = [];
  for (let i = 0; i < dim; i++) {
    rows[i] = [];
    for (let j = 0; j < dim; j++) {
      let sum = 0;
      for (const v of vectors) {
        sum += (v.components[i] - m.components[i]) * (v.components[j] - m.components[j]);
      }
      rows[i][j] = sum / (vectors.length - 1);
    }
  }
  return new Matrix(rows);
}
''')
    print("Created: /app/lib/src/plugins/statistics.ts")
    print("  - Bug 12: implemented mean() and covarianceMatrix()")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Diagnosing and fixing module resolution issues ===\n")

    fix_lib_package_json()
    print()
    fix_lib_tsconfig()
    print()
    fix_consumer_tsconfig()
    print()
    fix_types_ts()
    print()
    fix_index_ts()
    print()
    fix_consumer_main()
    print()
    fix_matrix_ts()
    print()
    create_statistics_module()

    print("\n=== All 12 bugs fixed successfully ===")


if __name__ == "__main__":
    main()
