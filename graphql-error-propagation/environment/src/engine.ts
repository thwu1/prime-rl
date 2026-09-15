
/**
 * GraphQL Value Completion Engine
 *
 * Implements the CompleteValue algorithm from the GraphQL Specification
 * (October 2021), Section 6.4.3 — Value Completion, including:
 *   - Recursive value completion for NonNull, List, Object, Scalar, Enum
 *   - Non-Null error propagation to the nearest nullable ancestor
 *   - Scalar result coercion for the five built-in scalar types
 *   - Error path tracking through nested objects and list indices
 *
 * NOTE: This implementation contains defects that must be corrected.
 */

import type {
  TypeDescriptor,
  ExecutionResponse,
  GraphQLResponseError,
  ObjectTypeDescriptor,
} from './types.js';
import { FieldError } from './types.js';

// ─── Public API ──────────────────────────────────────────────────

/**
 * Complete a root object value according to its type descriptor.
 *
 * @param rootType  - An Object type descriptor for the query root
 * @param resolvedValues - A map of field names to resolved values
 * @returns A spec-compliant ExecutionResponse with data and errors
 */
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
    const innerResult = completeValue(
      type.ofType,
      value,
      path,
      errors,
      parentTypeName,
      fieldName,
    );
    if (innerResult === null || innerResult === undefined) {
      // Only add the "Cannot return null" message if no error was
      // already recorded at exactly this path.
      if (!errors.some((e) => pathsEqual(e.path, path))) {
        errors.push({
          message: `Cannot return null for non-nullable field ${parentTypeName}.${fieldName}.`,
          path: [...path],
        });
      }
      return null;
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
      const itemResult = completeValue(
        type.ofType,
        value[i],
        path, // item path
        errors,
        parentTypeName,
        fieldName,
      );
      results.push(itemResult);
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
    const completed = completeValue(
      fieldDef.type,
      fieldValue,
      fieldPath,
      errors,
      type.name,
      fieldName,
    );
    result[fieldName] = completed;
  }

  return result;
}

// ─── Scalar Result Coercion ──────────────────────────────────────

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

function pathsEqual(
  a: ReadonlyArray<string | number>,
  b: ReadonlyArray<string | number>,
): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}
