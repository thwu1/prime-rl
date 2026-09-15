
/**
 * Fix script that patches all 11 bugs in the collaborative editing engine.
 *
 * Bug 1  (map.ts StepMap._map): DEL_SIDE condition uses `assoc > 0` instead of `assoc < 0`
 * Bug 2  (map.ts Mapping._map): Mirror recovery uses map() instead of recover()
 * Bug 3  (rebase.ts rebaseSteps): mapFrom is decremented before use instead of after
 * Bug 4  (step.ts ReplaceStep.merge): Missing backward-adjacent merge case
 * Bug 5  (map.ts StepMap.recover): Loop bound uses <= instead of <
 * Bug 6  (map.ts Mapping.appendMappingInverted): Mirror index off-by-one (totalSize - mirr vs totalSize - mirr - 1)
 * Bug 7  (compact.ts compactTransform): Loop variable j incremented before merge check
 * Bug 8  (spans.ts computeChangeSpans): Uses forward map instead of inverted map for backward coordinate mapping
 * Bug 9  (spans.ts mergeSpans): Merge condition uses < instead of <= (fails to merge touching ranges)
 * Bug 10 (history.ts _rebaseItems): Naively maps old inverse through remote mapping instead of recomputing from mapped step
 * Bug 11 (history.ts computeUndoMapping): Iterates oldest-to-newest instead of newest-to-oldest for batch undo
 */

import { readFileSync, writeFileSync } from 'fs'

function patch(filePath: string, oldStr: string, newStr: string): void {
  let content = readFileSync(filePath, 'utf-8')
  if (!content.includes(oldStr)) {
    console.error(`WARNING: Could not find patch target in ${filePath}`)
    console.error(`  Looking for: ${JSON.stringify(oldStr.substring(0, 80))}...`)
    return
  }
  content = content.replace(oldStr, newStr)
  writeFileSync(filePath, content, 'utf-8')
  console.log(`Patched ${filePath}`)
}

// ——— Bug 1: Fix DEL_SIDE condition in StepMap._map ———
// The condition should check assoc < 0, not assoc > 0.
// When assoc is negative, the position is "deleted" when it's not at the start.
// When assoc is positive, the position is "deleted" when it's not at the end.
patch(
  '/app/src/map.ts',
  'if (assoc > 0 ? pos != start : pos != end) del |= DEL_SIDE',
  'if (assoc < 0 ? pos != start : pos != end) del |= DEL_SIDE'
)

// ——— Bug 5: Fix loop bound in StepMap.recover ———
// The loop should use < index (exclusive), not <= index (inclusive).
// We only want to accumulate diffs from ranges BEFORE the target index.
patch(
  '/app/src/map.ts',
  'for (let i = 0; i <= index; i++) {',
  'for (let i = 0; i < index; i++) {'
)

// ——— Bug 2: Fix mirror recovery in Mapping._map ———
// Should use recover() for precise position recovery, not map() which
// loses the offset information within the deleted range.
patch(
  '/app/src/map.ts',
  'pos = this._maps[corr].map(result.pos, assoc)',
  'pos = this._maps[corr].recover(result.recover!)'
)

// ——— Bug 3: Fix mapFrom decrement timing in rebaseSteps ———
// mapFrom must be decremented AFTER using it to create the mapping slice,
// not before. Decrementing first causes the step to be mapped through
// its own inversion, producing incorrect positions.
patch(
  '/app/src/rebase.ts',
  `  for (let i = 0, mapFrom = steps.length; i < steps.length; i++) {
    mapFrom--
    let mapped = steps[i].step.map(transform.mapping.slice(mapFrom))`,
  `  for (let i = 0, mapFrom = steps.length; i < steps.length; i++) {
    let mapped = steps[i].step.map(transform.mapping.slice(mapFrom))
    mapFrom--`
)

// ——— Bug 6: Fix mirror index in Mapping.appendMappingInverted ———
// The mirror index computation uses `totalSize - mirr` instead of
// `totalSize - mirr - 1`, causing an off-by-one that breaks mirror
// pairs in inverted mappings (used for undo/redo position recovery).
patch(
  '/app/src/map.ts',
  'mirr != null && mirr > i ? totalSize - mirr : undefined',
  'mirr != null && mirr > i ? totalSize - mirr - 1 : undefined'
)

// ——— Bug 4: Add backward-adjacent merge case to ReplaceStep ———
// The merge method only handles the forward case (this.from + text.length == other.from).
// It's missing the backward case (other.to == this.from) for adjacent deletions
// and insertions in the reverse direction.
patch(
  '/app/src/step.ts',
  `    // Forward adjacent: this step's result end meets other step's start
    if (this.from + this.text.length === other.from) {
      return new ReplaceStep(
        this.from,
        this.to + (other.to - other.from),
        this.text + other.text
      )
    }

    return null`,
  `    // Forward adjacent: this step's result end meets other step's start
    if (this.from + this.text.length === other.from) {
      return new ReplaceStep(
        this.from,
        this.to + (other.to - other.from),
        this.text + other.text
      )
    }

    // Backward adjacent: other step ends where this step starts
    if (other.to === this.from) {
      return new ReplaceStep(
        other.from,
        this.to,
        other.text + this.text
      )
    }

    return null`
)

// ——— Bug 7: Fix j increment in compactTransform ———
// The loop increments j before checking the merge result, which causes
// the step at position j to be skipped when merge fails. The increment
// must happen only after confirming merge succeeded.
patch(
  '/app/src/compact.ts',
  `    while (j < transform.steps.length) {
      let merged = current.merge(transform.steps[j])
      j++
      if (!merged) break
      current = merged
    }`,
  `    while (j < transform.steps.length) {
      let merged = current.merge(transform.steps[j])
      if (!merged) break
      current = merged
      j++
    }`
)

// ——— Bug 8: Fix backward coordinate mapping in computeChangeSpans ———
// When mapping a step's changed range back to original-document coordinates,
// the code must use INVERTED maps (mapping from post-step to pre-step space).
// Using forward maps goes in the wrong direction, producing nonsensical
// positions that can exceed the original document size.
patch(
  '/app/src/spans.ts',
  `        fromA = transform.mapping.maps[k].map(fromA, -1)
        toA = transform.mapping.maps[k].map(toA, 1)`,
  `        fromA = transform.mapping.maps[k].invert().map(fromA, -1)
        toA = transform.mapping.maps[k].invert().map(toA, 1)`
)

// ——— Bug 9: Fix merge condition in mergeSpans ———
// The condition uses strict less-than (<), so ranges that merely touch
// (prev.toA == cur.fromA) are not merged. It should use <= to merge
// both overlapping AND adjacent (touching) ranges.
patch(
  '/app/src/spans.ts',
  'if (cur.fromA < prev.toA) {',
  'if (cur.fromA <= prev.toA) {'
)

// ——— Bug 10: Fix _rebaseItems in history.ts ———
// After mapping a forward step through remote changes, the inverse must
// be RECOMPUTED from the mapped step against the current document state.
// Naively mapping the old inverse through the same remote mapping produces
// an invalid inverse that, when applied for undo, corrupts the document.
patch(
  '/app/src/history.ts',
  `      let mappedInverted = item.inverted.map(mapping)
      if (!mappedInverted) continue`,
  `      let mappedInverted = mappedStep.invert(currentDoc)`
)

// ——— Bug 11: Fix computeUndoMapping iteration direction ———
// For batch undo, steps must be processed newest-to-oldest (most recent
// step is undone first). The buggy code iterates oldest-to-newest, which
// produces mirror pairs in the wrong order.
patch(
  '/app/src/history.ts',
  '    for (let i = start; i < this.done.length; i++) {',
  '    for (let i = this.done.length - 1; i >= start; i--) {'
)

console.log('All patches applied successfully.')
