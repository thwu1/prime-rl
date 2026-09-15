import { Position } from './types';

export default function equals(p1: Position, p2: Position): boolean {
  if (p1[0] === p2[0]) {
    if (p1[1] === p2[1]) {
      return true;
    } else {
      return false;
    }
  }
  return false;
}
