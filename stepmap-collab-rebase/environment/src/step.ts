import { Doc } from './doc.js'
import { StepMap, Mappable, MapResult } from './map.js'

/**
 * The result of applying a step. Contains either a new document or a
 * failure message.
 */
export class StepResult {
  constructor(
    /** The transformed document, if successful. */
    readonly doc: Doc | null,
    /** The failure message, if unsuccessful. */
    readonly failed: string | null
  ) {}

  static ok(doc: Doc): StepResult { return new StepResult(doc, null) }
  static fail(message: string): StepResult { return new StepResult(null, message) }
}

/**
 * A step object represents an atomic change. It generally applies
 * only to the document it was created for, since the positions
 * stored in it will only make sense for that document.
 */
export abstract class Step {
  abstract apply(doc: Doc): StepResult
  abstract getMap(): StepMap
  abstract invert(doc: Doc): Step
  abstract map(mapping: Mappable): Step | null
  merge(_other: Step): Step | null { return null }
  abstract toJSON(): any
}

/**
 * Replace a range of the document with new text. When text is empty,
 * this is a deletion. When from === to, this is an insertion.
 */
export class ReplaceStep extends Step {
  constructor(
    /** The start position of the replaced range. */
    readonly from: number,
    /** The end position of the replaced range. */
    readonly to: number,
    /** The text to insert. */
    readonly text: string
  ) {
    super()
  }

  apply(doc: Doc): StepResult {
    if (this.from < 0 || this.to > doc.size || this.from > this.to)
      return StepResult.fail("Invalid range for ReplaceStep")
    return StepResult.ok(doc.replace(this.from, this.to, this.text))
  }

  getMap(): StepMap {
    return new StepMap([this.from, this.to - this.from, this.text.length])
  }

  invert(doc: Doc): Step {
    return new ReplaceStep(this.from, this.from + this.text.length, doc.textBetween(this.from, this.to))
  }

  map(mapping: Mappable): Step | null {
    let fromResult = mapping.mapResult(this.from, 1)
    let toResult = this.from == this.to ? fromResult : mapping.mapResult(this.to, -1)
    if (fromResult.deletedAcross && toResult.deletedAcross) return null
    return new ReplaceStep(fromResult.pos, Math.max(fromResult.pos, toResult.pos), this.text)
  }

  merge(other: Step): Step | null {
    if (!(other instanceof ReplaceStep)) return null

    // Forward adjacent: this step's result end meets other step's start
    if (this.from + this.text.length === other.from) {
      return new ReplaceStep(
        this.from,
        this.to + (other.to - other.from),
        this.text + other.text
      )
    }

    return null
  }

  toJSON(): any {
    return { type: "replace", from: this.from, to: this.to, text: this.text }
  }

  toString(): string {
    return `ReplaceStep(${this.from}, ${this.to}, ${JSON.stringify(this.text)})`
  }
}
