import signedArea from './signed_area';
import SweepEvent from './sweep_event';
import { Position } from './types';

export default function compareEvents(e1: SweepEvent, e2: SweepEvent): number {
  const p1 = e1.point;
  const p2 = e2.point;

  if (p1[0] > p2[0]) return 1;
  if (p1[0] < p2[0]) return -1;

  if (p1[1] !== p2[1]) return p1[1] > p2[1] ? 1 : -1;

  return specialCases(e1, e2, p1, p2);
}

function specialCases(e1: SweepEvent, e2: SweepEvent, p1: Position, p2: Position): number {
  if (e1.left !== e2.left)
    return e1.left ? 1 : -1;

  if (signedArea(p1, e1.otherEvent!.point, e2.otherEvent!.point) !== 0) {
    return (!e1.isBelow(e2.otherEvent!.point)) ? 1 : -1;
  }

  return (!e1.isSubject && e2.isSubject) ? 1 : -1;
}
