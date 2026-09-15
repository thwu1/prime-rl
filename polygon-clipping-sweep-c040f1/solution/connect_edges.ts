import compareEvents from './compare_events';
import Contour from './contour';
import SweepEvent from './sweep_event';

function orderEvents(sortedEvents: SweepEvent[]): SweepEvent[] {
  let event: SweepEvent, i: number, len: number, tmpEvent: SweepEvent, tmpPos: number;
  const resultEvents: SweepEvent[] = [];
  for (i = 0, len = sortedEvents.length; i < len; i++) {
    event = sortedEvents[i];
    if ((event.left && event.inResult) ||
      (!event.left && event.otherEvent!.inResult)) {
      resultEvents.push(event);
    }
  }
  let sorted = false;
  while (!sorted) {
    sorted = true;
    for (i = 0, len = resultEvents.length; i < len; i++) {
      if ((i + 1) < len &&
        compareEvents(resultEvents[i], resultEvents[i + 1]) === 1) {
        tmpEvent = resultEvents[i];
        resultEvents[i] = resultEvents[i + 1];
        resultEvents[i + 1] = tmpEvent;
        sorted = false;
      }
    }
  }

  for (i = 0, len = resultEvents.length; i < len; i++) {
    event = resultEvents[i];
    event.otherPos = i;
  }

  for (i = 0, len = resultEvents.length; i < len; i++) {
    event = resultEvents[i];
    if (!event.left) {
      tmpPos = event.otherPos;
      event.otherPos = event.otherEvent!.otherPos;
      event.otherEvent!.otherPos = tmpPos;
    }
  }

  return resultEvents;
}

function nextPos(pos: number, resultEvents: SweepEvent[], processed: Record<number, boolean>, origPos: number): number {
  let newPos = pos + 1,
    p = resultEvents[pos].point,
    p1: any;
  const length = resultEvents.length;

  if (newPos < length)
    p1 = resultEvents[newPos].point;

  while (newPos < length && p1[0] === p[0] && p1[1] === p[1]) {
    if (!processed[newPos]) {
      return newPos;
    } else {
      newPos++;
    }
    if (newPos < length) {
      p1 = resultEvents[newPos].point;
    }
  }

  newPos = pos - 1;

  while (processed[newPos] && newPos > origPos) {
    newPos--;
  }

  return newPos;
}

function initializeContourFromContext(
  event: SweepEvent,
  contours: Contour[],
  contourId: number
): Contour {
  const contour = new Contour();
  if (event.prevInResult != null) {
    const prevInResult = event.prevInResult;
    const lowerContourId = prevInResult.outputContourId;
    const lowerResultTransition = prevInResult.resultTransition;
    if (lowerResultTransition > 0) {
      const lowerContour = contours[lowerContourId];
      if (lowerContour.holeOf != null) {
        const parentContourId = lowerContour.holeOf;
        contours[parentContourId].holeIds.push(contourId);
        contour.holeOf = parentContourId;
        contour.depth = contours[lowerContourId].depth;
      } else {
        contours[lowerContourId].holeIds.push(contourId);
        contour.holeOf = lowerContourId;
        contour.depth = contours[lowerContourId].depth + 1;
      }
    } else {
      contour.holeOf = null;
      contour.depth = contours[lowerContourId].depth;
    }
  } else {
    contour.holeOf = null;
    contour.depth = 0;
  }
  return contour;
}

export default function connectEdges(sortedEvents: SweepEvent[]): Contour[] {
  let i: number, len: number;
  const resultEvents = orderEvents(sortedEvents);

  const processed: Record<number, boolean> = {};
  const contours: Contour[] = [];

  for (i = 0, len = resultEvents.length; i < len; i++) {

    if (processed[i]) {
      continue;
    }

    const contourId = contours.length;
    const contour = initializeContourFromContext(resultEvents[i], contours, contourId);

    const markAsProcessed = (pos: number) => {
      processed[pos] = true;
      if (pos < resultEvents.length && resultEvents[pos]) {
        resultEvents[pos].outputContourId = contourId;
      }
    };

    let pos = i;
    let origPos = i;

    const initial = resultEvents[i].point;
    contour.points.push(initial);

    while (true) {
      markAsProcessed(pos);

      pos = resultEvents[pos].otherPos;

      markAsProcessed(pos);
      contour.points.push(resultEvents[pos].point);

      pos = nextPos(pos, resultEvents, processed, origPos);

      if (pos == origPos || pos >= resultEvents.length || !resultEvents[pos]) {
        break;
      }
    }

    contours.push(contour);
  }

  return contours;
}
