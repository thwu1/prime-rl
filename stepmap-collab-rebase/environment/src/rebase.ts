import { Step } from './step.js'
import { Transform } from './transform.js'

/**
 * A step that can be rebased: it stores both the step itself and its
 * inverse (computed at the time the step was first applied), along
 * with a reference to the originating transform.
 */
export class Rebaseable {
  constructor(
    readonly step: Step,
    readonly inverted: Step,
    readonly origin: Transform
  ) {}
}

/**
 * Undo a given set of steps, apply a set of other steps, and then
 * redo them. This is the core algorithm for collaborative editing
 * convergence via operational transformation.
 *
 * The function modifies `transform` in place, appending steps to it.
 * Returns the successfully rebased steps as new Rebaseable objects.
 *
 * @param steps - The local (unconfirmed) steps to rebase
 * @param over - The remote steps received from the authority
 * @param transform - The transform to build upon (starts from the
 *   local document with all unconfirmed steps applied)
 */
export function rebaseSteps(
  steps: readonly Rebaseable[],
  over: readonly Step[],
  transform: Transform
): Rebaseable[] {
  // Phase 1: Undo all local steps (apply their inverses in reverse order)
  for (let i = steps.length - 1; i >= 0; i--) {
    transform.step(steps[i].inverted)
  }

  // Phase 2: Apply all remote steps
  for (let i = 0; i < over.length; i++) {
    transform.step(over[i])
  }

  // Phase 3: Remap and reapply each local step through the combined
  // mapping of undos + remote steps + already-reapplied steps
  let result: Rebaseable[] = []
  for (let i = 0, mapFrom = steps.length; i < steps.length; i++) {
    mapFrom--
    let mapped = steps[i].step.map(transform.mapping.slice(mapFrom))
    if (mapped && !transform.maybeStep(mapped).failed) {
      transform.mapping.setMirror(mapFrom, transform.steps.length - 1)
      result.push(new Rebaseable(
        mapped,
        mapped.invert(transform.docs[transform.docs.length - 1]),
        steps[i].origin
      ))
    }
  }
  return result
}
