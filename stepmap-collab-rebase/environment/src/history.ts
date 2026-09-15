import { Step } from './step.js'
import { StepMap, Mapping, Mappable } from './map.js'
import { Doc } from './doc.js'
import { Transform } from './transform.js'

/**
 * A single item in the undo/redo history. Stores the forward step,
 * its inverse, the step's position map, and the cursor position
 * before the step was applied.
 */
export interface HistoryItem {
  /** The step that was applied */
  step: Step
  /** The inverse of the step (can undo it) */
  inverted: Step
  /** The step's position map */
  map: StepMap
  /** Cursor position before this step was applied */
  selectionBefore: number
}

/**
 * Manages undo/redo history for a collaborative editing session.
 *
 * The history tracks applied steps and their inverses, supporting:
 * - Single undo/redo via applyUndo/applyRedo
 * - Batch undo position mapping via computeUndoMapping
 * - Rebasing history through concurrent remote edits
 *
 * When remote edits arrive, rebaseHistory must be called to update
 * all stored steps and positions so they remain valid in the new
 * document state. This requires recomputing inverse steps against
 * the rebased document rather than naively remapping old inverses.
 */
export class UndoHistory {
  /** Steps that have been applied and can be undone */
  done: HistoryItem[] = []
  /** Steps that have been undone and can be redone */
  undone: HistoryItem[] = []

  /**
   * Record a new edit in the history. The step's inverse is computed
   * from the pre-edit document. Recording clears the redo stack.
   */
  record(step: Step, doc: Doc, selBefore: number): void {
    this.done.push({
      step,
      inverted: step.invert(doc),
      map: step.getMap(),
      selectionBefore: selBefore
    })
    this.undone = []
  }

  /**
   * Undo the most recent edit by applying its stored inverse to the
   * given transform. Returns the pre-edit cursor position, or null
   * if there is nothing to undo.
   */
  applyUndo(transform: Transform): number | null {
    if (this.done.length === 0) return null
    let item = this.done.pop()!
    transform.step(item.inverted)
    this.undone.push(item)
    return item.selectionBefore
  }

  /**
   * Redo the most recently undone edit by re-applying the stored
   * forward step. Returns the post-edit cursor position, or null
   * if there is nothing to redo.
   */
  applyRedo(transform: Transform): number | null {
    if (this.undone.length === 0) return null
    let item = this.undone.pop()!
    transform.step(item.step)
    this.done.push(item)
    return item.map.map(item.selectionBefore, 1)
  }

  /**
   * Rebase all stored history items through a set of remote changes.
   * Each item's step, inverse, position map, and stored cursor are
   * updated so they remain valid in the new document state.
   *
   * @param mapping - The mapping representing remote changes
   * @param newDoc - The document state after remote changes (before
   *   any local steps are re-applied)
   */
  rebaseHistory(mapping: Mapping, newDoc: Doc): void {
    this.done = this._rebaseItems(this.done, mapping, newDoc)
    this.undone = this._rebaseItems(this.undone, mapping, newDoc)
  }

  /** @internal */
  private _rebaseItems(items: HistoryItem[], mapping: Mapping, doc: Doc): HistoryItem[] {
    let result: HistoryItem[] = []
    let currentDoc = doc
    for (let item of items) {
      let mappedStep = item.step.map(mapping)
      if (!mappedStep) continue

      let mappedInverted = item.inverted.map(mapping)
      if (!mappedInverted) continue

      result.push({
        step: mappedStep,
        inverted: mappedInverted,
        map: mappedStep.getMap(),
        selectionBefore: mapping.map(item.selectionBefore, 1)
      })

      let stepResult = mappedStep.apply(currentDoc)
      if (!stepResult.failed) currentDoc = stepResult.doc!
    }
    return result
  }

  /**
   * Compute a combined Mapping that represents the effect of undoing
   * the last `count` items. The mapping uses mirror pairs so that
   * positions within edited regions can be precisely recovered.
   *
   * For batch undo, the most recently applied step must be undone
   * first (newest-to-oldest order). Each step contributes a forward
   * map (representing what happened) paired with its inverse map
   * (representing the undo), connected by a mirror pair for lossless
   * position recovery.
   */
  computeUndoMapping(count: number): Mapping | null {
    if (count > this.done.length || count <= 0) return null

    let mapping = new Mapping()
    let start = this.done.length - count

    for (let i = start; i < this.done.length; i++) {
      let fwdIdx = mapping.maps.length
      mapping.appendMap(this.done[i].map)
      let invIdx = mapping.maps.length
      mapping.appendMap(this.done[i].map.invert())
      mapping.setMirror(fwdIdx, invIdx)
    }

    return mapping
  }
}
