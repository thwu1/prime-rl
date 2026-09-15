import type { Vector } from "@mathkit/linalg";

export function formatVector(v: Vector): string {
  return `[${v.components.map(c => c.toFixed(2)).join(", ")}]`;
}
