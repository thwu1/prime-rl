import { Identifiable, Timestamped } from "./core";
import { User } from "./models";

export interface EventMap {
  "user:created": User;
  "user:deleted": Identifiable;
  "entity:updated": Identifiable & Timestamped;
}

export type EventPayload<K extends keyof EventMap> = EventMap[K];

export type UnwrapArray<T> = T extends Array<infer U> ? U : T;

export type AuditEntry = [Identifiable & Timestamped, User, string];

export function createEventBus(
  handlers: Map<string, ((payload: Identifiable) => void)[]>
): {
  emit: <K extends keyof EventMap>(event: K, payload: EventPayload<K>) => void;
} {
  throw new Error("Not implemented");
}
