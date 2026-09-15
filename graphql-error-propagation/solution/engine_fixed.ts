
/**
 * GraphQL Value Completion Engine — CORRECTED IMPLEMENTATION
 *
 * Fixes applied:
 * 1. NonNull error propagation via exception-based signaling (NonNullViolation)
 * 2. completeObjectValue catches NonNullViolation and returns null (object becomes null)
 * 3. List item error paths include numeric index
 * 4. Int scalar coercion checks 32-bit signed integer boundaries
 * 5. Float scalar coercion rejects NaN and Infinity (non-finite values)
 * 6. ID scalar coercion accepts integer values (serialized as strings)
 * 7. List returns null when a NonNull item violates
 * 8. Only one error per NonNull propagation chain (no duplicate intermediate errors)
 */

import type {
  TypeDescriptor,
  ExecutionResponse,
  GraphQLResponseError,
  ObjectTypeDescriptor,
} from './types.js';
import { FieldError } from './types.js';

// ─── NonNull Violation Signal ────────────────────────────────────

class NonNullViolation extends Error {
  constructor() {
    super('NonNull violation');
    this.name = 'NonNullViolation';
  }
}

// ─── Public API ──────────────────────────────────────────────────

export function executeCompletion(
  rootType: ObjectTypeDescriptor,
  resolvedValues: Record<string, unknown>,
): ExecutionResponse {
  const errors: GraphQLResponseError[] = [];
  const data = completeObjectValue(rootType, resolvedValues, [], errors);

  if (errors.length > 0) {
    return { data, errors };
  }
  return { data };
}

// ─── Core Completion ─────────────────────────────────────────────

function completeValue(
  type: TypeDescriptor,
  value: unknown,
  path: ReadonlyArray<string | number>,
  errors: GraphQLResponseError[],
  parentTypeName: string,
  fieldName: string,
): unknown {
  // ── NonNull handling ───────────────────────────────────────────
  if (type.kind === 'NonNull') {
    const errorCountBefore = errors.length;
    let innerResult: unknown;
    try {
      innerResult = completeValue(
        type.ofType,
        value,
        path,
        errors,
        parentTypeName,
        fieldName,
      );
    } catch (e) {
      if (e instanceof NonNullViolation) {
        // Child already recorded its error — just propagate upward.
        throw e;
      }
      throw e;
    }
    if (innerResult === null || innerResult === undefined) {
      // Only add "Cannot return null" if no error was recorded during
      // inner completion (i.e., value was genuinely null, not a FieldError).
      if (errors.length === errorCountBefore) {
        errors.push({
          message: `Cannot return null for non-nullable field ${parentTypeName}.${fieldName}.`,
          path: [...path],
        });
      }
      throw new NonNullViolation();
    }
    return innerResult;
  }

  // ── Null / undefined ──────────────────────────────────────────
  if (value === null || value === undefined) {
    return null;
  }

  // ── FieldError (resolver-level error) ─────────────────────────
  if (value instanceof FieldError) {
    errors.push({
      message: value.message,
      path: [...path],
    });
    return null;
  }

  // ── List ──────────────────────────────────────────────────────
  if (type.kind === 'List') {
    if (!Array.isArray(value)) {
      errors.push({
        message: `Expected Iterable, but did not find one for field "${parentTypeName}.${fieldName}".`,
        path: [...path],
      });
      return null;
    }
    const results: unknown[] = [];
    for (let i = 0; i < value.length; i++) {
      try {
        const itemResult = completeValue(
          type.ofType,
          value[i],
          [...path, i],  // include list index in path
          errors,
          parentTypeName,
          fieldName,
        );
        results.push(itemResult);
      } catch (e) {
        if (e instanceof NonNullViolation) {
          // NonNull item violated → entire list becomes null
          return null;
        }
        throw e;
      }
    }
    return results;
  }

  // ── Scalar ────────────────────────────────────────────────────
  if (type.kind === 'Scalar') {
    return coerceScalarResult(
      type.name,
      value,
      path,
      errors,
      parentTypeName,
      fieldName,
    );
  }

  // ── Enum ──────────────────────────────────────────────────────
  if (type.kind === 'Enum') {
    const strValue = typeof value === 'string' ? value : String(value);
    if (!type.values.includes(strValue)) {
      errors.push({
        message: `Expected a value of type "${type.name}" but received: ${inspect(value)}`,
        path: [...path],
      });
      return null;
    }
    return strValue;
  }

  // ── Object ────────────────────────────────────────────────────
  if (type.kind === 'Object') {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      errors.push({
        message: `Expected value of type "${type.name}" but received: ${inspect(value)}`,
        path: [...path],
      });
      return null;
    }
    return completeObjectValue(
      type,
      value as Record<string, unknown>,
      path,
      errors,
    );
  }

  return null;
}

// ─── Object Value Completion ─────────────────────────────────────

function completeObjectValue(
  type: ObjectTypeDescriptor,
  value: Record<string, unknown>,
  path: ReadonlyArray<string | number>,
  errors: GraphQLResponseError[],
): Record<string, unknown> | null {
  const result: Record<string, unknown> = {};

  for (const [fieldName, fieldDef] of Object.entries(type.fields)) {
    const fieldPath = [...path, fieldName];
    const fieldValue = value[fieldName];
    try {
      const completed = completeValue(
        fieldDef.type,
        fieldValue,
        fieldPath,
        errors,
        type.name,
        fieldName,
      );
      result[fieldName] = completed;
    } catch (e) {
      if (e instanceof NonNullViolation) {
        // A NonNull field in this object violated — the entire object
        // becomes null. Return null so the caller can decide whether
        // to propagate further (NonNull parent) or stop (nullable parent).
        return null;
      }
      throw e;
    }
  }

  return result;
}

// ─── Scalar Result Coercion ──────────────────────────────────────

const GRAPHQL_MAX_INT = 2147483647;
const GRAPHQL_MIN_INT = -2147483648;

function coerceScalarResult(
  scalarName: string,
  value: unknown,
  path: ReadonlyArray<string | number>,
  errors: GraphQLResponseError[],
  parentTypeName: string,
  fieldName: string,
): unknown {
  switch (scalarName) {
    // ── Int ────────────────────────────────────────────────────
    case 'Int': {
      if (typeof value === 'boolean') {
        return value ? 1 : 0;
      }
      if (typeof value === 'number') {
        if (!Number.isInteger(value)) {
          errors.push({
            message: `Int cannot represent non-integer value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        if (value > GRAPHQL_MAX_INT || value < GRAPHQL_MIN_INT) {
          errors.push({
            message: `Int cannot represent non 32-bit signed integer value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        return value;
      }
      if (typeof value === 'string') {
        const num = Number(value);
        if (value === '' || !Number.isInteger(num)) {
          errors.push({
            message: `Int cannot represent non-integer value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        if (num > GRAPHQL_MAX_INT || num < GRAPHQL_MIN_INT) {
          errors.push({
            message: `Int cannot represent non 32-bit signed integer value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        return num;
      }
      errors.push({
        message: `Int cannot represent non-integer value: ${inspect(value)}`,
        path: [...path],
      });
      return null;
    }

    // ── Float ──────────────────────────────────────────────────
    case 'Float': {
      if (typeof value === 'boolean') {
        return value ? 1.0 : 0.0;
      }
      if (typeof value === 'number') {
        if (!Number.isFinite(value)) {
          errors.push({
            message: `Float cannot represent non numeric value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        return value;
      }
      if (typeof value === 'string') {
        const num = Number(value);
        if (value === '' || !Number.isFinite(num)) {
          errors.push({
            message: `Float cannot represent non numeric value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        return num;
      }
      errors.push({
        message: `Float cannot represent non numeric value: ${inspect(value)}`,
        path: [...path],
      });
      return null;
    }

    // ── String ─────────────────────────────────────────────────
    case 'String': {
      if (typeof value === 'string') {
        return value;
      }
      if (typeof value === 'boolean') {
        return value ? 'true' : 'false';
      }
      if (typeof value === 'number') {
        if (!Number.isFinite(value)) {
          errors.push({
            message: `String cannot represent value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        return String(value);
      }
      errors.push({
        message: `String cannot represent value: ${inspect(value)}`,
        path: [...path],
      });
      return null;
    }

    // ── Boolean ────────────────────────────────────────────────
    case 'Boolean': {
      if (typeof value === 'boolean') {
        return value;
      }
      if (typeof value === 'number') {
        if (!Number.isFinite(value)) {
          errors.push({
            message: `Boolean cannot represent a non boolean value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        return value !== 0;
      }
      errors.push({
        message: `Boolean cannot represent a non boolean value: ${inspect(value)}`,
        path: [...path],
      });
      return null;
    }

    // ── ID ─────────────────────────────────────────────────────
    case 'ID': {
      if (typeof value === 'string') {
        return value;
      }
      if (typeof value === 'number') {
        if (!Number.isInteger(value)) {
          errors.push({
            message: `ID cannot represent value: ${inspect(value)}`,
            path: [...path],
          });
          return null;
        }
        return String(value);
      }
      errors.push({
        message: `ID cannot represent value: ${inspect(value)}`,
        path: [...path],
      });
      return null;
    }

    default: {
      errors.push({
        message: `Unknown scalar type: ${scalarName}`,
        path: [...path],
      });
      return null;
    }
  }
}

// ─── Helpers ─────────────────────────────────────────────────────

function inspect(value: unknown): string {
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';
  if (typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `[${value.map(inspect).join(', ')}]`;
  if (typeof value === 'object') return `{ ${Object.entries(value!).map(([k, v]) => `${k}: ${inspect(v)}`).join(', ')} }`;
  return String(value);
}
