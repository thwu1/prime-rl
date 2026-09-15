import { NORMAL, EdgeType } from './edge_type';
import { Position } from './types';


export default class SweepEvent {
  left: boolean;
  point: Position;
  otherEvent?: SweepEvent;
  isSubject: boolean;
  type: EdgeType;
  inOut: boolean;
  otherInOut: boolean;
  prevInResult: SweepEvent | null;
  resultTransition: number;
  otherPos: number;
  outputContourId: number;
  isExteriorRing: boolean;
  contourId?: number;

  constructor(point: Position, left: boolean, otherEvent?: SweepEvent, isSubject?: boolean, edgeType?: EdgeType) {
    this.left = left;
    this.point = point;
    this.otherEvent = otherEvent;
    this.isSubject = isSubject ?? false;
    this.type = edgeType || NORMAL;
    this.inOut = false;
    this.otherInOut = false;
    this.prevInResult = null;
    this.resultTransition = 0;
    this.otherPos = -1;
    this.outputContourId = -1;
    this.isExteriorRing = true;
  }

  isBelow(p: Position): boolean {
    const p0 = this.point, p1 = this.otherEvent!.point;
    return this.left
      ? (p0[0] - p[0]) * (p1[1] - p[1]) - (p1[0] - p[0]) * (p0[1] - p[1]) > 0
      : (p1[0] - p[0]) * (p0[1] - p[1]) - (p0[0] - p[0]) * (p1[1] - p[1]) > 0;
  }

  isAbove(p: Position): boolean {
    return !this.isBelow(p);
  }

  isVertical(): boolean {
    return this.point[0] === this.otherEvent!.point[0];
  }

  get inResult(): boolean {
    return this.resultTransition !== 0;
  }

  clone(): SweepEvent {
    const copy = new SweepEvent(
      this.point, this.left, this.otherEvent, this.isSubject, this.type);
    copy.contourId        = this.contourId;
    copy.resultTransition = this.resultTransition;
    copy.prevInResult     = this.prevInResult;
    copy.isExteriorRing   = this.isExteriorRing;
    copy.inOut            = this.inOut;
    copy.otherInOut       = this.otherInOut;
    return copy;
  }
}
