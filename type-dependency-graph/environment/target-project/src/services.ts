import { Identifiable } from "./core";
import { User, Post } from "./models";

export interface CrudService<T extends Identifiable> {
  findById(id: string): Promise<T | undefined>;
  findAll(filter?: Partial<T>): Promise<T[]>;
  create(data: Omit<T, "id">): Promise<T>;
  update(id: string, data: Partial<T>): Promise<T>;
  delete(id: string): Promise<boolean>;
}

export interface UserCrudService extends CrudService<User> {
  getUserByEmail(email: string): Promise<User | undefined>;
}

export type ServiceResult<T> =
  | { success: true; data: T }
  | { success: false; error: string };

export function createUserService(
  crud: CrudService<User>
): {
  getUser: (id: string) => Promise<ServiceResult<User>>;
  getUserPosts: (userId: string) => Promise<ServiceResult<Post[]>>;
} {
  throw new Error("Not implemented");
}
