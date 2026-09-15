import SweepEvent from "./sweep_event";
import Queue from "tinyqueue";


/**
 * Handle possible intersection between two sweep event segments.
 * If their segments intersect, subdivide as needed and enqueue new events.
 *
 * @returns 0 if no meaningful intersection, positive otherwise
 */
export default function possibleIntersection(
  se1: SweepEvent,
  se2: SweepEvent,
  queue: Queue<SweepEvent>
): number {
  // TODO: implement
  return 0;
}
