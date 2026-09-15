import { Doc } from './doc.js'
import { Mapping } from './map.js'
import { Step, StepResult } from './step.js'

/**
 * Abstraction to build up and track an array of steps representing a
 * document transformation.
 */
export class Transform {
  /** The steps in this transform. */
  readonly steps: Step[] = []
  /** The documents before each of the steps. */
  readonly docs: Doc[] = []
  /** A mapping with the maps for each of the steps in this transform. */
  readonly mapping: Mapping = new Mapping()

  /** Create a transform that starts with the given document. */
  constructor(
    /** The current document (the result of applying the steps). */
    public doc: Doc
  ) {}

  /** The starting document. */
  get before(): Doc { return this.docs.length ? this.docs[0] : this.doc }

  /** Apply a new step in this transform, saving the result. Throws an
   * error when the step fails. */
  step(step: Step): this {
    let result = this.maybeStep(step)
    if (result.failed) throw new Error("Transform.step failed: " + result.failed)
    return this
  }

  /** Try to apply a step in this transformation, ignoring it if it
   * fails. Returns the step result. */
  maybeStep(step: Step): StepResult {
    let result = step.apply(this.doc)
    if (!result.failed) this.addStep(step, result.doc!)
    return result
  }

  /** True when the document has been changed (when there are any steps). */
  get docChanged(): boolean {
    return this.steps.length > 0
  }

  /** @internal */
  addStep(step: Step, doc: Doc): void {
    this.docs.push(this.doc)
    this.steps.push(step)
    this.mapping.appendMap(step.getMap())
    this.doc = doc
  }
}
