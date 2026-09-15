import { Step } from './step.js'
import { Transform } from './transform.js'

/**
 * Compact a transform by merging adjacent compatible steps using
 * Step.merge(). Returns a new Transform with potentially fewer
 * steps that produces the same final document. The resulting
 * transform maintains correct intermediate documents and position
 * mappings.
 */
export function compactTransform(transform: Transform): Transform {
  if (transform.steps.length <= 1) return transform

  let result = new Transform(transform.before)
  let i = 0

  while (i < transform.steps.length) {
    let current = transform.steps[i]
    let j = i + 1

    // Attempt to merge current with subsequent compatible steps
    while (j < transform.steps.length) {
      let merged = current.merge(transform.steps[j])
      j++
      if (!merged) break
      current = merged
    }

    // Apply the (possibly merged) step to the compacted transform
    result.step(current)
    i = j
  }

  return result
}
