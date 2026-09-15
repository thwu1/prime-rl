import signedArea    from './signed_area';
import compareEvents from './compare_events';
import equals        from './equals';
import SweepEvent from './sweep_event';
import { Position } from './types';

export default function compareSegments(le1: SweepEvent, le2: SweepEvent): number {
  if (le1 === le2) return 0;

  if (signedArea(le1.point, le1.otherEvent!.point, le2.point) !== 0 ||
    signedArea(le1.point, le1.otherEvent!.point, le2.otherEvent!.point) !== 0) {

    if (equals(le1.point, le2.point)) return le1.isBelow(le2.otherEvent!.point) ? -1 : 1;

    if (le1.point[0] === le2.point[0]) return le1.point[1] < le2.point[1] ? -1 : 1;

    if (compareEvents(le1, le2) === 1) return le2.isAbove(le1.point) ? -1 : 1;

    return le1.isBelow(le2.point) ? -1 : 1;
  }

  if (le1.isSubject === le2.isSubject) {
    let p1: Position = le1.point, p2: Position = le2.point;
    if (p1[0] === p2[0] && p1[1] === p2[1]) {
      p1 = le1.otherEvent!.point; p2 = le2.otherEvent!.point;
      if (p1[0] === p2[0] && p1[1] === p2[1]) return 0;
      else return (le1.contourId ?? 0) > (le2.contourId ?? 0) ? 1 : -1;
    }
  } else {
    return le1.isSubject ? -1 : 1;
  }

  return compareEvents(le1, le2) === 1 ? 1 : -1;
}
