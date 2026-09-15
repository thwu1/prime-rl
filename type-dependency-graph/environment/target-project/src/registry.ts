import { Identifiable } from "./core";
import { User } from "./models";

export interface RegistryEntry<T extends Identifiable> {
  item: T;
  registry: Registry<T>;
  metadata: EntryMetadata;
}

export interface Registry<T extends Identifiable> {
  entries: RegistryEntry<T>[];
  owner: User;
}

export type EntryMetadata = {
  source: RegistryEntry<Identifiable>;
  timestamp: number;
};
