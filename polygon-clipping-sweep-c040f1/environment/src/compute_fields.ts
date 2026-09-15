import {
  NORMAL,
  SAME_TRANSITION,
  DIFFERENT_TRANSITION,
  NON_CONTRIBUTING,
} from "./edge_type";
import { INTERSECTION, UNION, DIFFERENCE, XOR } from "./operation";
import SweepEvent from "./sweep_event";


export default function computeFields(
  event: SweepEvent,
  prev: SweepEvent | null,
  operation: number
): void {
  // TODO: Implement
}
