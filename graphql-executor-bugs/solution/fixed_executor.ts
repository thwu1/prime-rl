/**
 * Fixed GraphQL execution engine.
 *
 * Uses the 'graphql' package for SDL parsing and type-system utilities,
 * but implements its own field resolution, value completion, and error
 * handling logic following the GraphQL specification.
 *
 * Fixes applied:
 * 1.  Non-Null handler throws FieldError to propagate null upward
 * 2.  List completion creates per-element path nodes with index
 * 3.  collectFields uses alias for response name
 * 4.  collectFields handles FRAGMENT_SPREAD
 * 5.  doesFragmentTypeApply checks union membership
 * 6.  valueFromAST resolves variables from the variables map
 * 7.  shouldIncludeNode correctly handles @include (not inverted)
 * 8.  executeGraphQL processes variable definitions for default values
 * 9.  completeValue calls serialize() on leaf type values
 * 10. resolveFieldValue uses ?? instead of || for falsy value integrity
 * 11. getFieldArguments extracts arguments from AST and applies schema defaults
 * 12. resolveFieldValue calls function values with coerced arguments
 */


import {
  buildSchema,
  parse,
  Kind,
  isNonNullType,
  isListType,
  isObjectType,
  isAbstractType,
  isLeafType,
  isInterfaceType,
  isUnionType,
  getNamedType,
} from 'graphql';

import type {
  DocumentNode,
  FieldNode,
  FragmentDefinitionNode,
  GraphQLSchema,
  GraphQLObjectType,
  GraphQLOutputType,
  GraphQLUnionType,
  SelectionSetNode,
  OperationDefinitionNode,
  ValueNode,
} from 'graphql';

// ======================== Public Types ========================

export interface GQLError {
  message: string;
  path: Array<string | number>;
}

export interface ExecutionResult {
  data: Record<string, unknown> | null;
  errors?: GQLError[];
}

// ======================== Path Tracking ========================

interface PathNode {
  prev: PathNode | null;
  key: string | number;
}

function createPath(prev: PathNode | null, key: string | number): PathNode {
  return { prev, key };
}

function pathToArray(path: PathNode | null): Array<string | number> {
  const segments: Array<string | number> = [];
  let current = path;
  while (current !== null) {
    segments.unshift(current.key);
    current = current.prev;
  }
  return segments;
}

// ======================== Null Propagation ========================

class FieldError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FieldError';
  }
}

// ======================== AST Value Extraction ========================

function valueFromAST(
  valueNode: ValueNode,
  variables: Record<string, unknown>,
): unknown {
  switch (valueNode.kind) {
    case Kind.STRING:
    case Kind.ENUM:
      return (valueNode as any).value;
    case Kind.INT:
      return parseInt((valueNode as any).value, 10);
    case Kind.FLOAT:
      return parseFloat((valueNode as any).value);
    case Kind.BOOLEAN:
      return (valueNode as any).value;
    case Kind.NULL:
      return null;
    case Kind.VARIABLE:
      // FIX 6: Look up the variable value from the variables map
      return variables[(valueNode as any).name.value];
    case Kind.LIST:
      return ((valueNode as any).values as ValueNode[]).map(
        (v) => valueFromAST(v, variables),
      );
    case Kind.OBJECT: {
      const obj: Record<string, unknown> = {};
      for (const field of (valueNode as any).fields) {
        obj[field.name.value] = valueFromAST(field.value, variables);
      }
      return obj;
    }
    default:
      return null;
  }
}

// ======================== Directive Handling ========================

function shouldIncludeNode(
  selection: any,
  variables: Record<string, unknown>,
): boolean {
  for (const directive of selection.directives ?? []) {
    const name = directive.name.value;
    if (name !== 'skip' && name !== 'include') continue;

    const ifArg = directive.arguments?.find(
      (a: any) => a.name.value === 'if',
    );
    if (!ifArg) continue;

    const value = !!valueFromAST(ifArg.value, variables);

    if (name === 'skip' && value) return false;
    // FIX 7: @include excludes when value is false, not when true
    if (name === 'include' && !value) return false;
  }
  return true;
}

// ======================== Field Argument Extraction ========================

function getFieldArguments(
  fieldNode: FieldNode,
  fieldDef: any,
  variables: Record<string, unknown>,
): Record<string, unknown> {
  const args: Record<string, unknown> = {};

  // FIX 11: Apply schema-defined argument default values
  for (const argDef of fieldDef.args ?? []) {
    if (argDef.defaultValue !== undefined) {
      args[argDef.name] = argDef.defaultValue;
    }
  }

  // Override with query-provided argument values from AST
  for (const astArg of fieldNode.arguments ?? []) {
    args[astArg.name.value] = valueFromAST(astArg.value, variables);
  }

  return args;
}

// ======================== Entry Point ========================

export function executeGraphQL(
  schemaSDL: string,
  query: string,
  rootValue: Record<string, unknown>,
  variables?: Record<string, unknown>,
): ExecutionResult {
  const schema = buildSchema(schemaSDL);
  const document = parse(query);
  const errors: GQLError[] = [];

  const operation = document.definitions.find(
    (d): d is OperationDefinitionNode => d.kind === Kind.OPERATION_DEFINITION,
  );
  if (!operation) {
    return { data: null, errors: [{ message: 'No operation found', path: [] }] };
  }

  const fragments: Record<string, FragmentDefinitionNode> = {};
  for (const def of document.definitions) {
    if (def.kind === Kind.FRAGMENT_DEFINITION) {
      fragments[def.name.value] = def;
    }
  }

  let rootType: GraphQLObjectType | null = null;
  if (operation.operation === 'query') {
    rootType = schema.getQueryType() ?? null;
  } else if (operation.operation === 'mutation') {
    rootType = schema.getMutationType() ?? null;
  }
  if (!rootType) {
    return { data: null, errors: [{ message: 'Missing root type', path: [] }] };
  }

  // FIX 8: Process variable definitions for default values
  const mergedVariables: Record<string, unknown> = {};
  for (const varDef of operation.variableDefinitions ?? []) {
    const varName = varDef.variable.name.value;
    if (varDef.defaultValue) {
      mergedVariables[varName] = valueFromAST(varDef.defaultValue as any, {});
    }
  }
  // Override defaults with explicitly provided variables
  Object.assign(mergedVariables, variables ?? {});

  try {
    const data = executeSelectionSet(
      schema, operation.selectionSet, rootType, rootValue,
      null, errors, fragments, mergedVariables,
    );
    const result: ExecutionResult = { data };
    if (errors.length > 0) {
      result.errors = errors;
    }
    return result;
  } catch (err) {
    if (err instanceof FieldError) {
      const result: ExecutionResult = { data: null };
      if (errors.length > 0) {
        result.errors = errors;
      }
      return result;
    }
    throw err;
  }
}

// ======================== Selection Set Execution ========================

function executeSelectionSet(
  schema: GraphQLSchema,
  selectionSet: SelectionSetNode,
  parentType: GraphQLObjectType,
  source: unknown,
  path: PathNode | null,
  errors: GQLError[],
  fragments: Record<string, FragmentDefinitionNode>,
  variables: Record<string, unknown>,
): Record<string, unknown> {
  const collected = collectFields(
    schema, parentType, selectionSet, fragments, variables,
  );
  const resultMap: Record<string, unknown> = {};

  for (const [responseName, fieldNodes] of collected) {
    const fieldNode = fieldNodes[0];
    const fieldName = fieldNode.name.value;

    if (fieldName === '__typename') {
      resultMap[responseName] = parentType.name;
      continue;
    }

    const fieldDef = parentType.getFields()[fieldName];
    if (!fieldDef) continue;

    const fieldPath = createPath(path, responseName);
    const args = getFieldArguments(fieldNode, fieldDef, variables);
    const resolved = resolveFieldValue(source, fieldName, args);

    try {
      const completed = completeValue(
        schema, fieldDef.type, fieldNodes, resolved,
        fieldPath, errors, fragments, variables, parentType.name,
      );
      resultMap[responseName] = completed;
    } catch (err) {
      if (err instanceof FieldError) {
        if (isNonNullType(fieldDef.type)) {
          throw err;
        }
        resultMap[responseName] = null;
      } else {
        throw err;
      }
    }
  }

  return resultMap;
}

// ======================== Field Collection ========================

function collectFields(
  schema: GraphQLSchema,
  parentType: GraphQLObjectType,
  selectionSet: SelectionSetNode,
  fragments: Record<string, FragmentDefinitionNode>,
  variables: Record<string, unknown>,
  visited: Set<string> = new Set(),
): Map<string, FieldNode[]> {
  const fieldMap = new Map<string, FieldNode[]>();

  for (const selection of selectionSet.selections) {
    if (!shouldIncludeNode(selection, variables)) {
      continue;
    }

    switch (selection.kind) {
      case Kind.FIELD: {
        // FIX 3: use alias when present
        const responseName = selection.alias?.value ?? selection.name.value;
        const existing = fieldMap.get(responseName) ?? [];
        existing.push(selection);
        fieldMap.set(responseName, existing);
        break;
      }

      case Kind.INLINE_FRAGMENT: {
        if (selection.typeCondition) {
          const typeName = selection.typeCondition.name.value;
          if (!doesFragmentTypeApply(schema, parentType, typeName)) {
            break;
          }
        }
        const nested = collectFields(
          schema, parentType, selection.selectionSet,
          fragments, variables, visited,
        );
        mergeFieldMaps(fieldMap, nested);
        break;
      }

      // FIX 4: handle named fragment spreads
      case Kind.FRAGMENT_SPREAD: {
        const fragName = selection.name.value;
        if (visited.has(fragName)) break;
        visited.add(fragName);

        const fragment = fragments[fragName];
        if (!fragment) break;

        const typeName = fragment.typeCondition.name.value;
        if (!doesFragmentTypeApply(schema, parentType, typeName)) {
          break;
        }

        const nested = collectFields(
          schema, parentType, fragment.selectionSet,
          fragments, variables, visited,
        );
        mergeFieldMaps(fieldMap, nested);
        break;
      }

      default:
        break;
    }
  }

  return fieldMap;
}

// ======================== Fragment Type Applicability ========================

function doesFragmentTypeApply(
  schema: GraphQLSchema,
  runtimeType: GraphQLObjectType,
  fragmentTypeName: string,
): boolean {
  if (runtimeType.name === fragmentTypeName) {
    return true;
  }

  const fragmentType = schema.getType(fragmentTypeName);
  if (!fragmentType) return false;

  if (isInterfaceType(fragmentType)) {
    return runtimeType.getInterfaces().some(
      (iface) => iface.name === fragmentTypeName,
    );
  }

  // FIX 5: check union membership
  if (isUnionType(fragmentType)) {
    return (fragmentType as GraphQLUnionType).getTypes().some(
      (t) => t.name === runtimeType.name,
    );
  }

  return false;
}

// ======================== Field Resolution ========================

function resolveFieldValue(
  source: unknown,
  fieldName: string,
  args: Record<string, unknown>,
): unknown {
  if (source == null) return null;
  if (typeof source === 'object') {
    // FIX 10: use ?? instead of || to preserve falsy values
    const val = (source as Record<string, unknown>)[fieldName] ?? null;
    // FIX 12: call function values with coerced arguments
    if (typeof val === 'function') {
      return (val as any)(args);
    }
    return val;
  }
  return null;
}

// ======================== Value Completion ========================

function completeValue(
  schema: GraphQLSchema,
  returnType: GraphQLOutputType,
  fieldNodes: FieldNode[],
  result: unknown,
  path: PathNode | null,
  errors: GQLError[],
  fragments: Record<string, FragmentDefinitionNode>,
  variables: Record<string, unknown>,
  parentTypeName: string,
): unknown {
  // ---- Non-Null wrapper ----
  if (isNonNullType(returnType)) {
    const innerType = returnType.ofType as GraphQLOutputType;
    const completed = completeValue(
      schema, innerType, fieldNodes, result,
      path, errors, fragments, variables, parentTypeName,
    );

    if (completed === null || completed === undefined) {
      const fieldName = fieldNodes[0].name.value;
      const msg = `Cannot return null for non-nullable field ${parentTypeName}.${fieldName}.`;
      errors.push({ message: msg, path: pathToArray(path) });
      // FIX 1: throw to propagate null upward through NonNull boundaries
      throw new FieldError(msg);
    }

    return completed;
  }

  // ---- Null result ----
  if (result === null || result === undefined) {
    return null;
  }

  // ---- List type ----
  if (isListType(returnType)) {
    if (!Array.isArray(result)) {
      return null;
    }
    const itemType = returnType.ofType as GraphQLOutputType;
    const completed: unknown[] = [];

    for (let index = 0; index < result.length; index++) {
      // FIX 2: include list index in the path
      const itemPath = createPath(path, index);

      try {
        const itemResult = completeValue(
          schema, itemType, fieldNodes, result[index],
          itemPath, errors, fragments, variables, parentTypeName,
        );
        completed.push(itemResult);
      } catch (err) {
        if (err instanceof FieldError) {
          if (isNonNullType(itemType)) {
            throw err;
          }
          completed.push(null);
        } else {
          throw err;
        }
      }
    }

    return completed;
  }

  // ---- Leaf types (scalar / enum) ----
  const namedType = getNamedType(returnType);
  if (!namedType) return null;

  if (isLeafType(namedType)) {
    // FIX 9: serialize through the scalar type's coercion
    return namedType.serialize(result);
  }

  // ---- Object / Abstract types ----
  let objectType: GraphQLObjectType;

  if (isObjectType(namedType)) {
    objectType = namedType;
  } else if (isAbstractType(namedType)) {
    const typeName = (result as Record<string, unknown>)?.__typename;
    if (typeof typeName !== 'string') {
      errors.push({
        message: `Abstract type "${namedType.name}" must resolve to an Object type at runtime via "__typename".`,
        path: pathToArray(path),
      });
      return null;
    }

    const resolved = schema.getType(typeName);
    if (!resolved || !isObjectType(resolved)) {
      errors.push({
        message: `Abstract type "${namedType.name}" resolved to invalid type "${typeName}".`,
        path: pathToArray(path),
      });
      return null;
    }

    objectType = resolved;
  } else {
    return null;
  }

  const subSelection = mergeSelectionSets(fieldNodes);
  if (!subSelection) return result;

  return executeSelectionSet(
    schema, subSelection, objectType, result,
    path, errors, fragments, variables,
  );
}

// ======================== Helpers ========================

function mergeSelectionSets(fieldNodes: FieldNode[]): SelectionSetNode | null {
  const all: any[] = [];
  for (const node of fieldNodes) {
    if (node.selectionSet) {
      all.push(...node.selectionSet.selections);
    }
  }
  if (all.length === 0) return null;
  return { kind: Kind.SELECTION_SET, selections: all } as SelectionSetNode;
}

function mergeFieldMaps(
  target: Map<string, FieldNode[]>,
  source: Map<string, FieldNode[]>,
): void {
  for (const [key, nodes] of source) {
    const existing = target.get(key) ?? [];
    existing.push(...nodes);
    target.set(key, existing);
  }
}
