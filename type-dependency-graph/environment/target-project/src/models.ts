import { Identifiable, Timestamped, Permission, Versioned } from "./core";

export interface User extends Identifiable, Timestamped {
  name: string;
  email: string;
  permissions: Permission[];
}

export interface Post extends Identifiable, Timestamped, Versioned {
  title: string;
  body: string;
  author: User;
}

export type UserSummary = Pick<User, "id" | "name">;
