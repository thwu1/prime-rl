import { Vector, Matrix, getPlatformId, Dimension } from "@mathkit/linalg";
import { fromLike, type VectorLike } from "@mathkit/linalg/types";
import { Matrix as MatrixDirect } from "@mathkit/linalg/matrix";
import { rotate2D } from "@mathkit/linalg/plugins/transform";
import { lerp } from "@mathkit/linalg/plugins/interpolate";
import { mean, covarianceMatrix } from "@mathkit/linalg/plugins/statistics";
import { formatVector } from "./helpers";

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
