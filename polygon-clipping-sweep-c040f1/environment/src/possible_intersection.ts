import divideSegment from "./divide_segment";
import intersection from "./segment_intersection";
import equals from "./equals";
import compareEvents from "./compare_events";
import SweepEvent from "./sweep_event";
import {
  NON_CONTRIBUTING,
  SAME_TRANSITION,
  DIFFERENT_TRANSITION,
} from "./edge_type";
import Queue from "tinyqueue";


export default function possibleIntersection(
  se1: SweepEvent,
  se2: SweepEvent,
  queue: Queue<SweepEvent>
): number {
  // TODO: Implement
  return 0;
}
