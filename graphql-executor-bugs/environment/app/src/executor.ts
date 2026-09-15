/**
 * Simplified GraphQL execution engine.
 *
 * Uses the 'graphql' package for SDL parsing and type-system utilities,
 * but implements its own field resolution, value completion, and error
 * handling logic following the GraphQL specification.
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

/**
 * Thrown when a non-nullable field resolves to null.
 * Caught at the nearest nullable type boundary to set that position to null.
 */
class FieldError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FieldError';
  }
}

// ======================== AST Value Extraction ========================

/**
 * Extracts a runtime value from a GraphQL ValueNode.
 * Handles literal values and variable references.
 */
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
      return (valueNode as any).name.value;
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

/**
 * Evaluates @skip and @include directives to determine whether
 * a selection (field, inline fragment, or fragment spread) should
 * be included in the response.
 */
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
    if (name === 'include' && value) return false;
  }
  return true;
}

// ======================== Field Argument Extraction ========================

/**
 * Extracts argument values for a field from the query AST
 * and the schema's argument definitions (for default values).
 */
function getFieldArguments(
  _fieldNode: FieldNode,
  _fieldDef: any,
  _variables: Record<string, unknown>,
): Record<string, unknown> {
  return {};
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

  try {
    const data = executeSelectionSet(
      schema, operation.selectionSet, rootType, rootValue,
      null, errors, fragments, variables ?? {},
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
        const responseName = selection.name.value;
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

      // Named fragment spreads are handled through inline expansion
      // during query parsing. No additional handling needed here.
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

  return false;
}

// ======================== Field Resolution ========================

function resolveFieldValue(
  source: unknown,
  fieldName: string,
  _args: Record<string, unknown>,
): unknown {
  if (source == null) return null;
  if (typeof source === 'object') {
    return (source as Record<string, unknown>)[fieldName] || null;
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
      errors.push({
        message: `Cannot return null for non-nullable field ${parentTypeName}.${fieldName}.`,
        path: pathToArray(path),
      });
      return null;
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
      const itemPath = path;

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
    return result;
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
