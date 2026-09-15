import { Transform } from './transform.js'

/**
 * A ChangeSpan describes a contiguous region where the original
 * and final documents differ. fromA/toA are positions in the
 * original document, fromB/toB in the final document.
 */
export interface ChangeSpan {
  /** Start position in the original document */
  fromA: number
  /** End position in the original document */
  toA: number
  /** Start position in the final document */
  fromB: number
  /** End position in the final document */
  toB: number
}

/**
 * Compute the set of change spans between a transform's base document
 * and its final document. Each span identifies a contiguous region
 * in the original document whose content was modified, along with
 * the corresponding region in the final document.
 *
 * The algorithm walks each step map in sequence:
 *   1. Existing spans' B-side positions are mapped forward through the
 *      new step (so they stay in the latest document's coordinate system).
 *   2. New change ranges from the step are collected. Their A-side
 *      positions are mapped backward through all preceding steps to
 *      obtain original-document coordinates.
 *
 * After all steps are processed, overlapping and adjacent spans are
 * merged and sorted by original-document position.
 */
export function computeChangeSpans(transform: Transform): ChangeSpan[] {
  if (transform.steps.length === 0) return []

  let spans: ChangeSpan[] = []

  for (let i = 0; i < transform.steps.length; i++) {
    let map = transform.mapping.maps[i]

    // Map existing spans' B-side positions forward through this step
    for (let j = 0; j < spans.length; j++) {
      let s = spans[j]
      spans[j] = {
        fromA: s.fromA,
        toA: s.toA,
        fromB: map.map(s.fromB, -1),
        toB: map.map(s.toB, 1)
      }
    }

    // Collect new change ranges from this step's map
    map.forEach((oldStart: number, oldEnd: number, newStart: number, newEnd: number) => {
      // Map oldStart/oldEnd back through preceding maps to obtain
      // positions in the original (pre-transform) document
      let fromA = oldStart, toA = oldEnd
      for (let k = i - 1; k >= 0; k--) {
        fromA = transform.mapping.maps[k].map(fromA, -1)
        toA = transform.mapping.maps[k].map(toA, 1)
      }
      spans.push({ fromA, toA, fromB: newStart, toB: newEnd })
    })
  }

  return mergeSpans(spans)
}

/**
 * Sort spans by original-document position and merge any that
 * overlap or are adjacent.
 */
function mergeSpans(spans: ChangeSpan[]): ChangeSpan[] {
  if (spans.length <= 1) return spans

  spans.sort((a, b) => a.fromA - b.fromA || a.toA - b.toA)

  let result: ChangeSpan[] = [spans[0]]
  for (let i = 1; i < spans.length; i++) {
    let prev = result[result.length - 1]
    let cur = spans[i]
    if (cur.fromA < prev.toA) {
      // Overlapping — merge into previous
      result[result.length - 1] = {
        fromA: prev.fromA,
        toA: Math.max(prev.toA, cur.toA),
        fromB: Math.min(prev.fromB, cur.fromB),
        toB: Math.max(prev.toB, cur.toB)
      }
    } else {
      result.push(cur)
    }
  }

  return result
}
