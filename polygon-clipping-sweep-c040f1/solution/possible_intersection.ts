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
  const inter = intersection(
    se1.point,
    se1.otherEvent!.point,
    se2.point,
    se2.otherEvent!.point
  );

  const nintersections = inter ? inter.length : 0;
  if (nintersections === 0) return 0;

  if (
    nintersections === 1 &&
    (equals(se1.point, se2.point) ||
      equals(se1.otherEvent!.point, se2.otherEvent!.point))
  ) {
    return 0;
  }

  if (nintersections === 2 && se1.isSubject === se2.isSubject) {
    return 0;
  }

  if (nintersections === 1) {
    if (
      !equals(se1.point, inter[0]) &&
      !equals(se1.otherEvent!.point, inter[0])
    ) {
      divideSegment(se1, inter[0], queue);
    }

    if (
      !equals(se2.point, inter[0]) &&
      !equals(se2.otherEvent!.point, inter[0])
    ) {
      divideSegment(se2, inter[0], queue);
    }
    return 1;
  }

  const events: SweepEvent[] = [];
  let leftCoincide = false;
  let rightCoincide = false;

  if (equals(se1.point, se2.point)) {
    leftCoincide = true;
  } else if (compareEvents(se1, se2) === 1) {
    events.push(se2, se1);
  } else {
    events.push(se1, se2);
  }

  if (equals(se1.otherEvent!.point, se2.otherEvent!.point)) {
    rightCoincide = true;
  } else if (compareEvents(se1.otherEvent!, se2.otherEvent!) === 1) {
    events.push(se2.otherEvent!, se1.otherEvent!);
  } else {
    events.push(se1.otherEvent!, se2.otherEvent!);
  }

  if ((leftCoincide && rightCoincide) || leftCoincide) {
    se2.type = NON_CONTRIBUTING;
    se1.type = se2.inOut === se1.inOut ? SAME_TRANSITION : DIFFERENT_TRANSITION;

    if (leftCoincide && !rightCoincide) {
      divideSegment(events[1].otherEvent!, events[0].point, queue);
    }
    return 2;
  }

  if (rightCoincide) {
    divideSegment(events[0], events[1].point, queue);
    return 3;
  }

  if (events[0] !== events[3].otherEvent!) {
    divideSegment(events[0], events[1].point, queue);
    divideSegment(events[1], events[2].point, queue);
    return 3;
  }

  divideSegment(events[0], events[1].point, queue);
  divideSegment(events[3].otherEvent!, events[2].point, queue);

  return 3;
}
