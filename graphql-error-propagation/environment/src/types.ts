
/**
 * GraphQL Value Completion Engine — Type Definitions
 *
 * Describes the GraphQL type system subset needed for value completion,
 * scalar result coercion, and Non-Null error propagation per the
 * GraphQL Specification (October 2021), Section 6.4.3.
 */

// ─── Type Descriptors ────────────────────────────────────────────

export type TypeDescriptor =
  | NonNullTypeDescriptor
  | NullableTypeDescriptor;

export interface NonNullTypeDescriptor {
  readonly kind: 'NonNull';
  readonly ofType: NullableTypeDescriptor;
}

export type NullableTypeDescriptor =
  | ScalarTypeDescriptor
  | EnumTypeDescriptor
  | ListTypeDescriptor
  | ObjectTypeDescriptor;

export interface ScalarTypeDescriptor {
  readonly kind: 'Scalar';
  readonly name: 'Int' | 'Float' | 'String' | 'Boolean' | 'ID';
}

export interface EnumTypeDescriptor {
  readonly kind: 'Enum';
  readonly name: string;
  readonly values: readonly string[];
}

export interface ListTypeDescriptor {
  readonly kind: 'List';
  readonly ofType: TypeDescriptor;
}

export interface ObjectTypeDescriptor {
  readonly kind: 'Object';
  readonly name: string;
  readonly fields: Readonly<Record<string, FieldDescriptor>>;
}

export interface FieldDescriptor {
  readonly type: TypeDescriptor;
}

// ─── Resolved Values ─────────────────────────────────────────────

/**
 * Sentinel class representing a resolver-level field error.
 * When encountered during value completion, the engine should
 * record the error and treat the field as having resolved to null.
 */
export class FieldError {
  public readonly message: string;
  constructor(message: string) {
    this.message = message;
  }
}

// ─── Response Types ──────────────────────────────────────────────

export interface GraphQLResponseError {
  readonly message: string;
  readonly path: ReadonlyArray<string | number>;
}

export interface ExecutionResponse {
  data: Record<string, unknown> | null;
  errors?: GraphQLResponseError[];
}
