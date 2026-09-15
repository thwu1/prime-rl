
import { StepMap, Mapping, MapResult } from './map.js'
import { ReplaceStep, StepResult, Step } from './step.js'
import { Doc } from './doc.js'
import { Transform } from './transform.js'
import { Rebaseable, rebaseSteps } from './rebase.js'
import { compactTransform } from './compact.js'
import { computeChangeSpans } from './spans.js'
import { UndoHistory } from './history.js'

// ——— Mini test framework ———

interface TestResult {
  group: string
  name: string
  passed: boolean
  error?: string
}

const results: TestResult[] = []

function test(group: string, name: string, fn: () => void) {
  try {
    fn()
    results.push({ group, name, passed: true })
  } catch (e: any) {
    results.push({ group, name, passed: false, error: e.message || String(e) })
  }
}

function assertEqual<T>(actual: T, expected: T, msg?: string) {
  if (actual !== expected) {
    throw new Error(msg || `Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`)
  }
}

function assertNotNull<T>(value: T | null | undefined, msg?: string): asserts value is T {
  if (value == null) {
    throw new Error(msg || `Expected non-null value, got ${value}`)
  }
}

function assertNull(value: any, msg?: string) {
  if (value != null) {
    throw new Error(msg || `Expected null, got ${JSON.stringify(value)}`)
  }
}

// ——— Helpers ———

function mk(...args: (number[] | { [from: number]: number })[]): Mapping {
  let mapping = new Mapping()
  args.forEach(arg => {
    if (Array.isArray(arg)) {
      mapping.appendMap(new StepMap(arg))
    } else {
      for (let from in arg) mapping.setMirror(+from, (arg as any)[from])
    }
  })
  return mapping
}

function buildRebaseables(
  baseContent: string,
  steps: [number, number, string][]
): { doc: Doc; rebaseables: Rebaseable[] } {
  let doc = new Doc(baseContent)
  let rebaseables: Rebaseable[] = []
  for (const [from, to, text] of steps) {
    let step = new ReplaceStep(from, to, text)
    let transform = new Transform(doc)
    let inverted = step.invert(doc)
    rebaseables.push(new Rebaseable(step, inverted, transform))
    let result = step.apply(doc)
    if (result.failed) throw new Error('Step failed: ' + result.failed)
    doc = result.doc!
  }
  return { doc, rebaseables }
}

function testRebase(
  baseContent: string,
  localSteps: [number, number, string][],
  remoteSteps: [number, number, string][]
): string {
  let { doc, rebaseables } = buildRebaseables(baseContent, localSteps)
  let remotes = remoteSteps.map(([f, t, txt]) => new ReplaceStep(f, t, txt))
  let transform = new Transform(doc)
  rebaseSteps(rebaseables, remotes, transform)
  return transform.doc.content
}

// ======================================================================
// TEST GROUP: basic_mapping — sanity checks (should pass even with bugs)
// ======================================================================

test("basic_mapping", "map_through_insertion", () => {
  let map = new StepMap([2, 0, 4])
  assertEqual(map.map(0), 0, "pos 0 should stay at 0")
  assertEqual(map.map(2, -1), 2, "pos 2 with left assoc stays at 2")
  assertEqual(map.map(2, 1), 6, "pos 2 with right assoc moves to 6")
  assertEqual(map.map(3), 7, "pos 3 should move to 7")
})

test("basic_mapping", "map_through_deletion", () => {
  let map = new StepMap([2, 4, 0])
  assertEqual(map.map(0), 0, "pos 0 stays at 0")
  assertEqual(map.map(7), 3, "pos 7 (after deletion) moves to 3")
})

test("basic_mapping", "map_through_replace", () => {
  let map = new StepMap([2, 4, 4])
  assertEqual(map.map(0), 0, "pos 0 stays at 0")
  assertEqual(map.map(8), 8, "pos 8 stays at 8 (same size replace)")
})

// ======================================================================
// TEST GROUP: deletion_flags — test MapResult.deleted correctness
// These tests verify the DEL_SIDE flag logic.
// ======================================================================

test("deletion_flags", "del_side_neg_assoc_at_deletion_end", () => {
  // Delete [0,2). Position 2 is at the end. With assoc=-1, the token
  // on the left (before) is the deleted content, so deleted should be true.
  let r = new StepMap([0, 2, 0]).mapResult(2, -1)
  assertEqual(r.deleted, true,
    "Position at deletion end with left assoc should be deleted")
  assertEqual(r.deletedBefore, true,
    "Token before position was deleted")
})

test("deletion_flags", "del_side_pos_assoc_at_deletion_start", () => {
  // Delete [2,4). Position 2 is at the start. With assoc=1, the token
  // on the right (after) is the deleted content, so deleted should be true.
  let r = new StepMap([2, 2, 0]).mapResult(2, 1)
  assertEqual(r.deleted, true,
    "Position at deletion start with right assoc should be deleted")
  assertEqual(r.deletedAfter, true,
    "Token after position was deleted")
})

test("deletion_flags", "del_side_neg_assoc_at_deletion_start", () => {
  // Delete [0,2). Position 0 is at the start. With assoc=-1, the
  // token on the left is NOT deleted (nothing to the left), so
  // deleted should be false.
  let r = new StepMap([0, 2, 0]).mapResult(0, -1)
  assertEqual(r.deleted, false,
    "Position at deletion start with left assoc should NOT be deleted")
})

test("deletion_flags", "del_side_pos_assoc_at_deletion_end", () => {
  // Delete [2,4). Position 4 is at the end. With assoc=1, the token
  // on the right is NOT deleted, so deleted should be false.
  let r = new StepMap([2, 2, 0]).mapResult(4, 1)
  assertEqual(r.deleted, false,
    "Position at deletion end with right assoc should NOT be deleted")
})

// ======================================================================
// TEST GROUP: recover_function — test StepMap.recover directly
// ======================================================================

test("recover_function", "recover_offset_within_insertion", () => {
  // StepMap([3, 0, 4]) is an insertion of 4 chars at position 3.
  // recover with index=0, offset=2 should give 3 + 2 = 5
  let map = new StepMap([3, 0, 4])
  let recoverValue = 0 + 2 * Math.pow(2, 16)  // makeRecover(0, 2)
  assertEqual(map.recover(recoverValue), 5,
    "recover(index=0, offset=2) for insertion at 3 should return 5")
})

test("recover_function", "recover_with_preceding_change", () => {
  // StepMap([2, 0, 3, 8, 0, 2]) — insert 3 chars at 2, then 2 chars at 8
  // recover with index=1, offset=1 should give:
  //   diff from ranges before index 1: ranges[2]-ranges[1] = 3-0 = 3
  //   return ranges[1*3] + 3 + 1 = 8 + 3 + 1 = 12
  let map = new StepMap([2, 0, 3, 8, 0, 2])
  let recoverValue = 1 + 1 * Math.pow(2, 16)  // makeRecover(1, 1)
  assertEqual(map.recover(recoverValue), 12,
    "recover should accumulate diff from preceding ranges only")
})

// ======================================================================
// TEST GROUP: mirror_recovery — test Mapping with mirrored maps
// These test lossless round-tripping through delete-then-reinsert pairs.
// ======================================================================

test("mirror_recovery", "delete_reinsert_preserves_inner_position", () => {
  // Map 0: delete 4 chars at pos 3 → StepMap([3, 4, 0])
  // Map 1: insert 2 chars at pos 3 → StepMap([3, 0, 2])
  // Mirror: {0: 1}
  // Position 4 (offset 1 inside deletion) should map to 4 via recovery.
  let mapping = mk([3, 4, 0], [3, 0, 2], { 0: 1 })
  let result = mapping.map(4, 1)
  assertEqual(result, 4,
    "Position inside deleted range should recover through mirror to 4")
})

test("mirror_recovery", "delete_reinsert_multiple_positions", () => {
  // Same setup: delete [3,7), insert 2 chars at 3. Mirror {0:1}.
  let mapping = mk([3, 4, 0], [3, 0, 2], { 0: 1 })

  // pos=5 (offset 2) → should recover to 5
  assertEqual(mapping.map(5, 1), 5,
    "Position 5 should recover to 5")

  // pos=3 (at start, assoc=1) → recover = null (at boundary), mapped normally
  // Through map 0: pos=3, at start of deletion, side=-1, result=3
  // recover=null because pos == (assoc<0 ? start : end) → pos==end → 3==7 → false
  // Actually pos == start here. recover = makeRecover(0, 0)
  // Mirror recovery: maps[1].recover(makeRecover(0, 0))
  //   = ranges[0] + 0 + 0 = 3
  assertEqual(mapping.map(3, 1), 3,
    "Position at deletion start should recover to 3")
})

test("mirror_recovery", "mirrored_delete_insert_roundtrip", () => {
  // Test the classic ProseMirror pattern: delete then reinsert same range
  // Map 0: delete [2,6) → StepMap([2, 4, 0])
  // Map 1: insert 4 chars at 2 → StepMap([2, 0, 4])
  // Mirror: {0: 1}
  let mapping = mk([2, 4, 0], [2, 0, 4], { 0: 1 })

  // All interior positions should map back to themselves
  for (let pos = 2; pos <= 6; pos++) {
    let mapped = mapping.map(pos, 1)
    assertEqual(mapped, pos,
      `Position ${pos} should round-trip to ${pos}`)
  }
  // Position outside the range should be unaffected
  assertEqual(mapping.map(0), 0, "Position before range unaffected")
  assertEqual(mapping.map(7), 7, "Position after range unaffected")
})

// ======================================================================
// TEST GROUP: step_merge — test ReplaceStep.merge
// ======================================================================

test("step_merge", "forward_adjacent_merge", () => {
  // Insert "ab" at 2, then insert "cd" at 4 (right after)
  let step1 = new ReplaceStep(2, 2, "ab")
  let step2 = new ReplaceStep(4, 4, "cd")
  let merged = step1.merge(step2)
  assertNotNull(merged, "Forward adjacent steps should merge")

  // Verify merged step produces same result as sequential application
  let doc = new Doc("0123456789")
  let afterBoth = step2.apply(step1.apply(doc).doc!).doc!
  let afterMerged = (merged as ReplaceStep).apply(doc).doc!
  assertEqual(afterMerged.content, afterBoth.content,
    "Merged step should produce same result as sequential application")
})

test("step_merge", "backward_adjacent_merge", () => {
  // Delete [4,6), then delete [2,4) — backward adjacent (other.to == this.from)
  let step1 = new ReplaceStep(4, 6, "")
  let step2 = new ReplaceStep(2, 4, "")
  let merged = step1.merge(step2)
  assertNotNull(merged, "Backward adjacent delete steps should merge")

  // Verify merged step produces same result
  let doc = new Doc("abcdefghij")
  let afterBoth = step2.apply(step1.apply(doc).doc!).doc!
  let afterMerged = (merged as ReplaceStep).apply(doc).doc!
  assertEqual(afterMerged.content, afterBoth.content,
    "Merged backward delete should produce same result")
})

test("step_merge", "non_adjacent_no_merge", () => {
  let step1 = new ReplaceStep(1, 2, "a")
  let step2 = new ReplaceStep(5, 6, "b")
  let merged = step1.merge(step2)
  assertNull(merged, "Non-adjacent steps should not merge")
})

test("step_merge", "backward_adjacent_insert_merge", () => {
  // Insert "cd" at 4, then insert "ab" at 4 (prepend at same position)
  // After step1: doc[4] = "cd...", after step2: doc[4] = "ab" then "cd..."
  // other.to (4) == this.from (4)
  let step1 = new ReplaceStep(4, 4, "cd")
  let step2 = new ReplaceStep(4, 4, "ab")
  let merged = step1.merge(step2)
  assertNotNull(merged, "Backward adjacent insert steps should merge")

  let doc = new Doc("0123456789")
  let afterBoth = step2.apply(step1.apply(doc).doc!).doc!
  let afterMerged = (merged as ReplaceStep).apply(doc).doc!
  assertEqual(afterMerged.content, afterBoth.content,
    "Merged backward insert should produce same result")
})

// ======================================================================
// TEST GROUP: rebase — test collaborative editing convergence
// ======================================================================

test("rebase", "non_overlapping_concurrent_inserts", () => {
  // Base: "abcdefgh"
  // Local: insert "X" at 3
  // Remote: insert "Y" at 6
  // Expected: "abcXdefYgh"
  let result = testRebase(
    "abcdefgh",
    [[3, 3, "X"]],
    [[6, 6, "Y"]]
  )
  assertEqual(result, "abcXdefYgh",
    "Non-overlapping inserts should both appear in result")
})

test("rebase", "replace_with_concurrent_insert_inside", () => {
  // Base: "abcdefgh"
  // Local: replace [2,5] with "XY"
  // Remote: insert "Z" at 1
  // Expected: "aZbXYfgh"
  //   (Remote insert is outside local replace range, both apply independently)
  let result = testRebase(
    "abcdefgh",
    [[2, 5, "XY"]],
    [[1, 1, "Z"]]
  )
  assertEqual(result, "aZbXYfgh",
    "Replace with concurrent insert should converge correctly")
})

test("rebase", "concurrent_deletions_non_overlapping", () => {
  // Base: "abcdefghij"
  // Local: delete [2,4] = "cd"
  // Remote: delete [6,8] = "gh"
  // Expected: "abefij"
  let result = testRebase(
    "abcdefghij",
    [[2, 4, ""]],
    [[6, 8, ""]]
  )
  assertEqual(result, "abefij",
    "Non-overlapping deletions should both apply")
})

// ======================================================================
// TEST GROUP: rebase_multi — multi-step rebase with mirror recovery
// ======================================================================

test("rebase_multi", "two_local_steps_with_remote_insert", () => {
  // Base: "abcdefghij" (10 chars)
  // Local step 0: insert "X" at 2 → "abXcdefghij"
  // Local step 1: insert "Y" at 7 → "abXcdefYghij"
  // Remote: insert "Z" at 5 → "abcdeZfghij"
  // Expected: "abXcdeZfYghij"
  //   X at base pos 2, Z at base pos 5, Y between f and g in base (pos 6)
  let result = testRebase(
    "abcdefghij",
    [[2, 2, "X"], [7, 7, "Y"]],
    [[5, 5, "Z"]]
  )
  assertEqual(result, "abXcdeZfYghij",
    "Two local inserts with one remote insert should converge")
})

test("rebase_multi", "local_delete_and_insert_with_remote", () => {
  // Base: "abcdefghij"
  // Local step 0: delete [3,7] = "defg" → "abchij"
  // Local step 1: insert "X" at 3 → "abcXhij"
  // Remote: insert "!" at 1 → "a!bcdefghij"
  // Expected: "a!bcXhij"
  //   Remote insert at 1, local delete [3,7] shifts right by 1 → delete [4,8],
  //   local insert X at 3 shifts right by 1 → insert at 4.
  //   Result: "a!bc" + delete defg + "X" + "hij" = "a!bcXhij"
  let result = testRebase(
    "abcdefghij",
    [[3, 7, ""], [3, 3, "X"]],
    [[1, 1, "!"]]
  )
  assertEqual(result, "a!bcXhij",
    "Local delete+insert with remote insert should converge correctly")
})

// ======================================================================
// TEST GROUP: step_inversion — verify step apply/invert round-trip
// ======================================================================

test("step_inversion", "insert_invert_roundtrip", () => {
  let doc = new Doc("hello world")
  let step = new ReplaceStep(5, 5, " beautiful")
  let result = step.apply(doc)
  assertNotNull(result.doc, "Insert should succeed")
  let inverse = step.invert(doc)
  let restored = inverse.apply(result.doc!)
  assertNotNull(restored.doc, "Inverse should succeed")
  assertEqual(restored.doc!.content, doc.content,
    "Applying step then inverse should restore original doc")
})

test("step_inversion", "delete_invert_roundtrip", () => {
  let doc = new Doc("hello beautiful world")
  let step = new ReplaceStep(5, 15, "")
  let result = step.apply(doc)
  assertNotNull(result.doc, "Delete should succeed")
  let inverse = step.invert(doc)
  let restored = inverse.apply(result.doc!)
  assertNotNull(restored.doc, "Inverse should succeed")
  assertEqual(restored.doc!.content, doc.content,
    "Applying delete then inverse should restore original doc")
})

test("step_inversion", "replace_invert_roundtrip", () => {
  let doc = new Doc("foo bar baz")
  let step = new ReplaceStep(4, 7, "QUUX")
  let result = step.apply(doc)
  assertNotNull(result.doc, "Replace should succeed")
  let inverse = step.invert(doc)
  let restored = inverse.apply(result.doc!)
  assertNotNull(restored.doc, "Inverse should succeed")
  assertEqual(restored.doc!.content, doc.content,
    "Applying replace then inverse should restore original doc")
})

// ======================================================================
// TEST GROUP: mapping_inversion — test Mapping.invert() correctness
// ======================================================================

test("mapping_inversion", "invert_simple_mapping_roundtrip", () => {
  // A simple mapping with no mirrors: insert 3 chars at position 5
  let mapping = mk([5, 0, 3])
  let inv = mapping.invert()

  // Positions before insertion point
  assertEqual(inv.map(mapping.map(0, 1), 1), 0, "Pos 0 roundtrip")
  assertEqual(inv.map(mapping.map(4, 1), 1), 4, "Pos 4 roundtrip")

  // Positions after insertion point
  assertEqual(inv.map(mapping.map(6, 1), 1), 6, "Pos 6 roundtrip")
  assertEqual(inv.map(mapping.map(10, 1), 1), 10, "Pos 10 roundtrip")
})

test("mapping_inversion", "invert_mirrored_mapping_roundtrip", () => {
  // Delete [2,6) then insert 4 at 2, with mirror pair — simulates undo/redo
  let mapping = mk([2, 4, 0], [2, 0, 4], {0: 1})
  let inv = mapping.invert()

  // All positions should survive the forward+inverse roundtrip
  for (let pos = 0; pos <= 8; pos++) {
    let fwd = mapping.map(pos, 1)
    let back = inv.map(fwd, 1)
    assertEqual(back, pos, `Position ${pos} should roundtrip (fwd=${fwd})`)
  }
})

test("mapping_inversion", "invert_multi_mirror_pair_roundtrip", () => {
  // Two independent mirrored pairs at different positions
  let mapping = new Mapping()
  mapping.appendMap(new StepMap([1, 2, 0]))  // 0: delete [1,3)
  mapping.appendMap(new StepMap([1, 0, 2]))  // 1: insert 2 at 1
  mapping.setMirror(0, 1)
  mapping.appendMap(new StepMap([5, 3, 0]))  // 2: delete [5,8)
  mapping.appendMap(new StepMap([5, 0, 3]))  // 3: insert 3 at 5
  mapping.setMirror(2, 3)

  let inv = mapping.invert()

  // Positions inside both mirrored ranges must roundtrip correctly
  for (let pos = 0; pos <= 10; pos++) {
    let fwd = mapping.map(pos, 1)
    let back = inv.map(fwd, 1)
    assertEqual(back, pos,
      `Position ${pos} should roundtrip through complex mirrored mapping (fwd=${fwd})`)
  }
})

// ======================================================================
// TEST GROUP: compact — test compactTransform
// ======================================================================

test("compact", "merge_adjacent_inserts", () => {
  let doc = new Doc("abcdef")
  let t = new Transform(doc)
  t.step(new ReplaceStep(2, 2, "X"))
  t.step(new ReplaceStep(3, 3, "Y"))
  t.step(new ReplaceStep(4, 4, "Z"))

  let compacted = compactTransform(t)
  assertEqual(compacted.doc.content, t.doc.content,
    "Compacted transform should produce same final document")
  assertEqual(compacted.steps.length < t.steps.length, true,
    "Compacted transform should have fewer steps than original")
})

test("compact", "non_adjacent_steps_preserved", () => {
  let doc = new Doc("abcdefghij")
  let t = new Transform(doc)
  t.step(new ReplaceStep(1, 2, "X"))
  t.step(new ReplaceStep(5, 6, "Y"))  // Not adjacent to first step

  let compacted = compactTransform(t)
  assertEqual(compacted.doc.content, t.doc.content,
    "Non-adjacent steps should produce same final document")
  assertEqual(compacted.steps.length, 2,
    "Non-adjacent steps should not be merged")
})

test("compact", "mixed_mergeable_and_non", () => {
  let doc = new Doc("abcdefghij")
  let t = new Transform(doc)
  t.step(new ReplaceStep(2, 2, "X"))   // Insert X at 2
  t.step(new ReplaceStep(3, 3, "Y"))   // Insert Y at 3 (adjacent to X)
  t.step(new ReplaceStep(8, 9, "Z"))   // Replace at 8, not adjacent

  let compacted = compactTransform(t)
  assertEqual(compacted.doc.content, t.doc.content,
    "Mixed steps should produce same final document")
  assertEqual(compacted.steps.length, 2,
    "First two should merge, third stays separate")
})

test("compact", "mapping_correctness", () => {
  let doc = new Doc("abcdefghij")
  let t = new Transform(doc)
  t.step(new ReplaceStep(2, 2, "XX"))   // Insert XX at 2
  t.step(new ReplaceStep(4, 4, "YY"))   // Insert YY at 4 (adjacent)

  let compacted = compactTransform(t)
  // Position 5 in original should map identically through both mappings
  let mappedOriginal = t.mapping.map(5, 1)
  let mappedCompacted = compacted.mapping.map(5, 1)
  assertEqual(mappedCompacted, mappedOriginal,
    "Compacted mapping should track positions identically to original")
})

test("compact", "backward_adjacent_delete_merge", () => {
  let doc = new Doc("abcdefghij")
  let t = new Transform(doc)
  t.step(new ReplaceStep(4, 6, ""))     // Delete [4,6)
  t.step(new ReplaceStep(2, 4, ""))     // Delete [2,4) — backward adjacent

  let compacted = compactTransform(t)
  assertEqual(compacted.doc.content, t.doc.content,
    "Backward adjacent deletes should compact to same document")
  assertEqual(compacted.steps.length, 1,
    "Backward adjacent deletes should merge into one step")
})

// ======================================================================
// TEST GROUP: change_spans — test computeChangeSpans
// ======================================================================

test("change_spans", "empty_transform", () => {
  let t = new Transform(new Doc("abcdefgh"))
  let spans = computeChangeSpans(t)
  assertEqual(spans.length, 0, "Empty transform should have no change spans")
})

test("change_spans", "single_deletion", () => {
  let doc = new Doc("abcdefgh")
  let t = new Transform(doc)
  t.step(new ReplaceStep(3, 5, ""))

  let spans = computeChangeSpans(t)
  assertEqual(spans.length, 1, "Should have one change span")
  assertEqual(spans[0].fromA, 3, "fromA should be 3")
  assertEqual(spans[0].toA, 5, "toA should be 5")
  assertEqual(spans[0].fromB, 3, "fromB should be 3")
  assertEqual(spans[0].toB, 3, "toB should be 3 (deletion)")
})

test("change_spans", "single_insertion", () => {
  let doc = new Doc("abcdef")
  let t = new Transform(doc)
  t.step(new ReplaceStep(2, 2, "XYZ"))

  let spans = computeChangeSpans(t)
  assertEqual(spans.length, 1, "Should have one change span")
  assertEqual(spans[0].fromA, 2, "fromA")
  assertEqual(spans[0].toA, 2, "toA (insertion, zero-width in original)")
  assertEqual(spans[0].fromB, 2, "fromB")
  assertEqual(spans[0].toB, 5, "toB (3 chars inserted)")
})

test("change_spans", "multi_step_coordinate_mapping", () => {
  // This test verifies correct backward mapping through preceding steps.
  // Step 0: insert "XY" at 2 → "abXYcdefgh" (shifts positions >= 2 by +2)
  // Step 1: delete [5,7) in post-step-0 doc → removes "de" → "abXYcfgh"
  //
  // Step 1's deleted range [5,7) must be mapped back through step 0's
  // INVERTED map to get original coordinates [3,5).
  // Using the forward map would incorrectly give [7,9).
  let doc = new Doc("abcdefgh")
  let t = new Transform(doc)
  t.step(new ReplaceStep(2, 2, "XY"))
  t.step(new ReplaceStep(5, 7, ""))

  let spans = computeChangeSpans(t)
  assertEqual(spans.length, 2, "Should have two separate change spans")
  // Span 0: insertion at original pos 2
  assertEqual(spans[0].fromA, 2, "span 0 fromA")
  assertEqual(spans[0].toA, 2, "span 0 toA")
  // Span 1: deletion mapped back to original pos 3-5
  assertEqual(spans[1].fromA, 3,
    "span 1 fromA should be 3 (mapped back through step 0 inversion)")
  assertEqual(spans[1].toA, 5,
    "span 1 toA should be 5 (mapped back through step 0 inversion)")
})

test("change_spans", "adjacent_spans_merge", () => {
  // Same-size replacements at adjacent ranges. The two spans touch
  // (first ends at 4, second starts at 4) and should merge into one.
  // Same-size maps don't shift positions, so this test isolates the
  // merge logic from coordinate-mapping correctness.
  let doc = new Doc("abcdefgh")
  let t = new Transform(doc)
  t.step(new ReplaceStep(2, 4, "XY"))   // Replace [2,4) with "XY"
  t.step(new ReplaceStep(4, 6, "ZW"))   // Replace [4,6) with "ZW"

  let spans = computeChangeSpans(t)
  assertEqual(spans.length, 1, "Touching spans should merge into one")
  assertEqual(spans[0].fromA, 2, "merged fromA")
  assertEqual(spans[0].toA, 6, "merged toA")
  assertEqual(spans[0].fromB, 2, "merged fromB")
  assertEqual(spans[0].toB, 6, "merged toB")
})

test("change_spans", "overlapping_multi_step_merge", () => {
  // Step 0: insert "XY" at 3 → "abcXYdefgh"
  // Step 1: replace [3,5) with "Z" → "abcZdefgh"
  // Both changes map to fromA=3 in original coordinates and should merge.
  // Net effect: insert "Z" at position 3.
  let doc = new Doc("abcdefgh")
  let t = new Transform(doc)
  t.step(new ReplaceStep(3, 3, "XY"))
  t.step(new ReplaceStep(3, 5, "Z"))

  let spans = computeChangeSpans(t)
  assertEqual(spans.length, 1, "Overlapping spans should merge")
  assertEqual(spans[0].fromA, 3, "merged fromA")
  assertEqual(spans[0].toA, 3, "merged toA (no original content deleted)")
  assertEqual(spans[0].fromB, 3, "merged fromB")
  assertEqual(spans[0].toB, 4, "merged toB (1 char 'Z' in final doc)")
})

test("change_spans", "non_adjacent_spans_separate", () => {
  // Two same-size replacements with a gap between them
  let doc = new Doc("abcdefghij")
  let t = new Transform(doc)
  t.step(new ReplaceStep(1, 2, "X"))    // Replace at 1
  t.step(new ReplaceStep(7, 8, "Y"))    // Replace at 7 (not adjacent)

  let spans = computeChangeSpans(t)
  assertEqual(spans.length, 2, "Non-adjacent spans should remain separate")
  assertEqual(spans[0].fromA, 1, "first span fromA")
  assertEqual(spans[0].toA, 2, "first span toA")
  assertEqual(spans[1].fromA, 7, "second span fromA")
  assertEqual(spans[1].toA, 8, "second span toA")
})

// ======================================================================
// TEST GROUP: history_basic — test basic undo/redo lifecycle
// ======================================================================

test("history_basic", "simple_undo_redo", () => {
  let doc = new Doc("hello world")
  let history = new UndoHistory()

  let step = new ReplaceStep(5, 5, " beautiful")
  history.record(step, doc, 5)
  let editedDoc = step.apply(doc).doc!
  assertEqual(editedDoc.content, "hello beautiful world")

  // Undo
  let t = new Transform(editedDoc)
  let sel = history.applyUndo(t)
  assertEqual(t.doc.content, "hello world", "Undo should restore original")
  assertEqual(sel, 5, "Selection should be at original position")

  // Redo
  let t2 = new Transform(t.doc)
  let sel2 = history.applyRedo(t2)
  assertEqual(t2.doc.content, "hello beautiful world", "Redo should reapply edit")
  assertNotNull(sel2)
})

test("history_basic", "record_clears_redo_stack", () => {
  let doc = new Doc("abcdef")
  let history = new UndoHistory()

  let step1 = new ReplaceStep(2, 2, "X")
  history.record(step1, doc, 2)
  doc = step1.apply(doc).doc!

  // Undo to create redo item
  let t = new Transform(doc)
  history.applyUndo(t)
  assertEqual(history.undone.length, 1, "Should have one undone item")

  // Record a new step — should clear redo stack
  let step2 = new ReplaceStep(0, 0, "Z")
  history.record(step2, t.doc, 0)
  assertEqual(history.undone.length, 0,
    "Recording a new step should clear the redo stack")
  assertEqual(history.done.length, 1,
    "Done stack should have the new step")
})

// ======================================================================
// TEST GROUP: history_rebase — test undo/redo after collaborative rebase
// ======================================================================

test("history_rebase", "undo_after_rebase_restores_correct_doc", () => {
  // Base: "abcdef"
  // Local edit: replace [2,4) with "XY" → "abXYef"
  // Remote edit: replace [3,4) with "ZW" → base becomes "abcZWef"
  //
  // After rebase, the mapped local step replaces [2,5) with "XY" on "abcZWef"
  // producing "abXYef". Undoing this should restore "abcZWef".
  //
  // A naive approach (just remapping the old inverse through the remote
  // mapping) produces a WRONG inverse that restores "abcdf" instead.
  // The correct fix is to recompute the inverse from the mapped step
  // and the actual document state.
  let baseDoc = new Doc("abcdef")
  let history = new UndoHistory()

  let step = new ReplaceStep(2, 4, "XY")
  history.record(step, baseDoc, 2)

  // Remote edit: replace [3,4) with "ZW"
  let remoteMapping = new Mapping()
  remoteMapping.appendMap(new StepMap([3, 1, 2]))
  let newBaseDoc = new Doc("abcZWef")

  // Rebase history through remote changes
  history.rebaseHistory(remoteMapping, newBaseDoc)

  // Get the rebased step and verify it produces expected doc
  assertEqual(history.done.length, 1, "Should still have one done item")
  let rebasedStep = history.done[0].step
  let currentDoc = rebasedStep.apply(newBaseDoc).doc!
  assertEqual(currentDoc.content, "abXYef",
    "Rebased step applied to new base should produce expected doc")

  // Now undo — this uses the stored inverse, which must be correct
  let transform = new Transform(currentDoc)
  let sel = history.applyUndo(transform)
  assertNotNull(sel)

  assertEqual(transform.doc.content, "abcZWef",
    "Undo after rebase should restore the rebased base document")
})

test("history_rebase", "redo_after_rebase_roundtrip", () => {
  // Same setup as above, but also test redo after undo
  let baseDoc = new Doc("abcdef")
  let history = new UndoHistory()

  let step = new ReplaceStep(2, 4, "XY")
  history.record(step, baseDoc, 2)

  let remoteMapping = new Mapping()
  remoteMapping.appendMap(new StepMap([3, 1, 2]))
  let newBaseDoc = new Doc("abcZWef")

  history.rebaseHistory(remoteMapping, newBaseDoc)

  let rebasedStep = history.done[0].step
  let currentDoc = rebasedStep.apply(newBaseDoc).doc!

  // Undo
  let t1 = new Transform(currentDoc)
  history.applyUndo(t1)

  // Redo from the undo result
  let t2 = new Transform(t1.doc)
  history.applyRedo(t2)

  assertEqual(t2.doc.content, "abXYef",
    "Redo after undo after rebase should produce the correctly edited document")
})

// ======================================================================
// TEST GROUP: history_mapping — test computeUndoMapping ordering
// ======================================================================

test("history_mapping", "batch_undo_mapping_newest_first", () => {
  // Record two steps. Batch undo mapping should process the most recent
  // step first (newest-to-oldest order).
  let doc = new Doc("abcdefghij")
  let history = new UndoHistory()

  // Step 0: insert "X" at 2 → map [2, 0, 1]
  let step0 = new ReplaceStep(2, 2, "X")
  history.record(step0, doc, 2)
  doc = step0.apply(doc).doc!

  // Step 1: delete [5,8) → map [5, 3, 0]
  let step1 = new ReplaceStep(5, 8, "")
  history.record(step1, doc, 5)
  doc = step1.apply(doc).doc!

  let mapping = history.computeUndoMapping(2)
  assertNotNull(mapping)
  assertEqual(mapping!.maps.length, 4,
    "Undo mapping for 2 items should have 4 maps (2 mirror pairs)")

  // First pair should correspond to step 1 (most recent, undone first)
  let firstMapRanges = mapping!.maps[0].ranges
  assertEqual(firstMapRanges[0], 5,
    "First map pair should be for step 1 (most recent) at position 5")

  // Second pair should correspond to step 0
  let thirdMapRanges = mapping!.maps[2].ranges
  assertEqual(thirdMapRanges[0], 2,
    "Second map pair should be for step 0 at position 2")
})

test("history_mapping", "batch_undo_mapping_overlapping_ranges", () => {
  // Test with overlapping ranges where order is critical
  let doc = new Doc("abcdefghij")
  let history = new UndoHistory()

  // Step 0: insert "XX" at 3 → map [3, 0, 2]
  let step0 = new ReplaceStep(3, 3, "XX")
  history.record(step0, doc, 3)
  doc = step0.apply(doc).doc!

  // Step 1: replace [4,7) with "Y" → map [4, 3, 1]
  // This range overlaps with step 0's insertion
  let step1 = new ReplaceStep(4, 7, "Y")
  history.record(step1, doc, 4)
  doc = step1.apply(doc).doc!

  let mapping = history.computeUndoMapping(2)
  assertNotNull(mapping)

  // First map should be step 1's (most recent), starting at pos 4
  let firstMap = mapping!.maps[0]
  assertEqual(firstMap.ranges[0], 4,
    "First map should correspond to step 1 (at position 4)")
  assertEqual(firstMap.ranges[1], 3,
    "First map oldSize should be 3")
  assertEqual(firstMap.ranges[2], 1,
    "First map newSize should be 1")
})

// ======================================================================
// Output results as JSON
// ======================================================================
console.log(JSON.stringify({ results }))
