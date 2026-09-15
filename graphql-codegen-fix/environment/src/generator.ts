import {
  parse,
  buildSchema,
  Kind,
  isObjectType,
  isInterfaceType,
  isUnionType,
  isEnumType,
  isScalarType,
  isInputObjectType,
  isListType,
  isNonNullType,
  getNamedType,
  type GraphQLSchema,
  type GraphQLObjectType,
  type GraphQLInterfaceType,
  type GraphQLUnionType,
  type GraphQLEnumType,
  type GraphQLInputObjectType,
  type GraphQLOutputType,
  type DocumentNode,
  type FragmentDefinitionNode,
  type OperationDefinitionNode,
  type SelectionSetNode,
  type FieldNode,
  type TypeNode,
} from 'graphql';

export interface CodegenConfig {
  scalars?: Record<string, string>;
}

interface FieldEntry {
  key: string;
  typeStr: string;
  optional: boolean;
}

interface GeneratorContext {
  schema: GraphQLSchema;
  fragments: Map<string, FragmentDefinitionNode>;
  config: CodegenConfig;
}

const DEFAULT_SCALARS: Record<string, string> = {
  String: 'string',
  Int: 'number',
  Float: 'number',
  Boolean: 'boolean',
  ID: 'string',
};

export function generate(
  schemaSource: string,
  operationSources: string[],
  config: CodegenConfig = {}
): string {
  const schema = buildSchema(schemaSource);
  const allDefs = operationSources
    .map(s => parse(s))
    .flatMap(d => [...d.definitions]);

  const fragments = new Map<string, FragmentDefinitionNode>();
  for (const def of allDefs) {
    if (def.kind === Kind.FRAGMENT_DEFINITION) {
      fragments.set(def.name.value, def);
    }
  }

  const ctx: GeneratorContext = { schema, fragments, config };
  const output: string[] = [];

  output.push(
    'export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };'
  );
  output.push('');

  // Emit enum types
  const typeMap = schema.getTypeMap();
  const enumTypes = Object.values(typeMap)
    .filter((t): t is GraphQLEnumType => isEnumType(t) && !t.name.startsWith('__'))
    .sort((a, b) => a.name.localeCompare(b.name));

  for (const enumType of enumTypes) {
    const values = enumType
      .getValues()
      .map(v => `  | '${v.name}'`)
      .join('\n');
    output.push(`export type ${enumType.name} =\n${values};`);
    output.push('');
  }

  // Emit input types
  const inputTypes = Object.values(typeMap)
    .filter(
      (t): t is GraphQLInputObjectType =>
        isInputObjectType(t) && !t.name.startsWith('__')
    )
    .sort((a, b) => a.name.localeCompare(b.name));

  for (const inputType of inputTypes) {
    output.push(emitInputType(ctx, inputType));
    output.push('');
  }

  // Emit fragment types
  for (const def of allDefs) {
    if (def.kind === Kind.FRAGMENT_DEFINITION) {
      const parentTypeName = def.typeCondition.name.value;
      const parentType = schema.getType(parentTypeName)!;
      const fields = resolveSelectionSet(
        ctx,
        def.selectionSet,
        parentType as GraphQLObjectType
      );
      output.push(
        `export type ${def.name.value}Fragment = ${formatObjectType(fields)};`
      );
      output.push('');
    }
  }

  // Emit operation types
  for (const def of allDefs) {
    if (def.kind === Kind.OPERATION_DEFINITION && def.name) {
      const opName = def.name.value;
      const opSuffix = capitalize(def.operation);

      output.push(emitVariablesType(ctx, def, `${opName}${opSuffix}Variables`));
      output.push('');

      const rootTypeName =
        def.operation === 'query'
          ? 'Query'
          : def.operation === 'mutation'
            ? 'Mutation'
            : 'Subscription';
      const rootType = schema.getType(rootTypeName) as GraphQLObjectType;
      const fields = resolveSelectionSet(ctx, def.selectionSet, rootType);
      output.push(
        `export type ${opName}${opSuffix} = ${formatObjectType(fields)};`
      );
      output.push('');
    }
  }

  return output.join('\n').trimEnd() + '\n';
}

/* ------------------------------------------------------------------ */
/*  Input types                                                        */
/* ------------------------------------------------------------------ */

function emitInputType(
  ctx: GeneratorContext,
  inputType: GraphQLInputObjectType
): string {
  const fields = inputType.getFields();
  const fieldStrs = Object.values(fields).map(f => {
    const tsType = resolveInputGraphQLType(ctx, f.type);
    const isRequired = isNonNullType(f.type);
    return `  ${f.name}${isRequired ? '' : '?'}: ${tsType};`;
  });
  return `export type ${inputType.name} = {\n${fieldStrs.join('\n')}\n};`;
}

/* ------------------------------------------------------------------ */
/*  Variables                                                          */
/* ------------------------------------------------------------------ */

function emitVariablesType(
  ctx: GeneratorContext,
  op: OperationDefinitionNode,
  typeName: string
): string {
  if (!op.variableDefinitions || op.variableDefinitions.length === 0) {
    return `export type ${typeName} = Exact<{ [key: string]: never }>;`;
  }

  const fields = op.variableDefinitions.map(v => {
    const name = v.variable.name.value;
    const tsType = resolveInputTypeNode(ctx, v.type);
    const isRequired = v.type.kind === Kind.NON_NULL_TYPE;
    return isRequired
      ? `  ${name}: ${tsType};`
      : `  ${name}?: ${tsType} | null;`;
  });

  return `export type ${typeName} = Exact<{\n${fields.join('\n')}\n}>;`;
}

/* ------------------------------------------------------------------ */
/*  Selection set resolution                                           */
/* ------------------------------------------------------------------ */

function resolveSelectionSet(
  ctx: GeneratorContext,
  selectionSet: SelectionSetNode,
  parentType: GraphQLObjectType | GraphQLInterfaceType
): FieldEntry[] {
  const fields: FieldEntry[] = [];

  for (const selection of selectionSet.selections) {
    switch (selection.kind) {
      case Kind.FIELD: {
        // Get the output key for this field
        const fieldName = selection.name.value;

        const objectType = parentType as GraphQLObjectType;
        const fieldDef = objectType.getFields()[selection.name.value];
        if (!fieldDef) continue;

        // Determine if field is optional
        const optional = false;

        if (selection.selectionSet) {
          const namedType = getNamedType(fieldDef.type);

          if (isUnionType(namedType) || isInterfaceType(namedType)) {
            const innerTypeStr = resolvePolymorphicSelectionSet(
              ctx,
              selection.selectionSet,
              namedType as GraphQLUnionType | GraphQLInterfaceType
            );
            const wrappedType = wrapOutputType(innerTypeStr, fieldDef.type);
            fields.push({ key: fieldName, typeStr: wrappedType, optional });
          } else {
            const innerFields = resolveSelectionSet(
              ctx,
              selection.selectionSet,
              namedType as GraphQLObjectType
            );
            const innerTypeStr = formatObjectType(innerFields);
            const wrappedType = wrapOutputType(innerTypeStr, fieldDef.type);
            fields.push({ key: fieldName, typeStr: wrappedType, optional });
          }
        } else {
          const tsType = resolveLeafOutputType(ctx, fieldDef.type);
          fields.push({ key: fieldName, typeStr: tsType, optional });
        }
        break;
      }

      case Kind.FRAGMENT_SPREAD: {
        // Look up the fragment definition by name
        const fragName = selection.name.value + 'Fragment';
        const fragment = ctx.fragments.get(fragName);
        if (fragment) {
          const fragTypeName = fragment.typeCondition.name.value;
          const fragType = ctx.schema.getType(
            fragTypeName
          ) as GraphQLObjectType;
          const fragFields = resolveSelectionSet(
            ctx,
            fragment.selectionSet,
            fragType
          );
          fields.push(...fragFields);
        }
        break;
      }

      case Kind.INLINE_FRAGMENT: {
        const typeName = selection.typeCondition?.name.value;
        const targetType = typeName
          ? (ctx.schema.getType(typeName) as GraphQLObjectType)
          : (parentType as GraphQLObjectType);
        const inlineFields = resolveSelectionSet(
          ctx,
          selection.selectionSet,
          targetType
        );
        for (const f of inlineFields) {
          f.optional = true;
          fields.push(f);
        }
        break;
      }
    }
  }

  return fields;
}

/* ------------------------------------------------------------------ */
/*  Polymorphic (union / interface) selection sets                     */
/* ------------------------------------------------------------------ */

function resolvePolymorphicSelectionSet(
  ctx: GeneratorContext,
  selectionSet: SelectionSetNode,
  parentType: GraphQLUnionType | GraphQLInterfaceType
): string {
  const allFields: FieldEntry[] = [];

  // Collect shared fields (fields directly on an interface)
  for (const selection of selectionSet.selections) {
    if (selection.kind === Kind.FIELD && isInterfaceType(parentType)) {
      const fieldDef = parentType.getFields()[selection.name.value];
      if (fieldDef) {
        const fieldName = selection.name.value;
        if (selection.selectionSet) {
          const namedType = getNamedType(fieldDef.type);
          const innerFields = resolveSelectionSet(
            ctx,
            selection.selectionSet,
            namedType as GraphQLObjectType
          );
          const innerTypeStr = formatObjectType(innerFields);
          const wrappedType = wrapOutputType(innerTypeStr, fieldDef.type);
          allFields.push({
            key: fieldName,
            typeStr: wrappedType,
            optional: false,
          });
        } else {
          const tsType = resolveLeafOutputType(ctx, fieldDef.type);
          allFields.push({ key: fieldName, typeStr: tsType, optional: false });
        }
      }
    }
  }

  // Collect inline fragment fields — merged flat into one object
  for (const selection of selectionSet.selections) {
    if (selection.kind === Kind.INLINE_FRAGMENT && selection.typeCondition) {
      const typeName = selection.typeCondition.name.value;
      const targetType = ctx.schema.getType(typeName) as GraphQLObjectType;
      const inlineFields = resolveSelectionSet(
        ctx,
        selection.selectionSet,
        targetType
      );
      for (const f of inlineFields) {
        f.optional = true;
        allFields.push(f);
      }
    }
  }

  return formatObjectType(allFields);
}

/* ------------------------------------------------------------------ */
/*  Output type resolution (leaf types — scalars, enums)               */
/* ------------------------------------------------------------------ */

function resolveLeafOutputType(ctx: GeneratorContext, gqlType: any): string {
  if (isNonNullType(gqlType)) {
    return resolveLeafOutputTypeInner(ctx, gqlType.ofType, false);
  }
  return resolveLeafOutputTypeInner(ctx, gqlType, true);
}

function resolveLeafOutputTypeInner(
  ctx: GeneratorContext,
  gqlType: any,
  nullable: boolean
): string {
  if (isListType(gqlType)) {
    // Resolve inner type for list items
    const innerNamedType = getNamedType(gqlType);
    const innerTsType = resolveScalarOrEnumType(ctx, innerNamedType as any);
    const result = `Array<${innerTsType} | null>`;
    return nullable ? `${result} | null` : result;
  }

  const tsType = resolveScalarOrEnumType(ctx, gqlType);
  return nullable ? `${tsType} | null` : tsType;
}

/* ------------------------------------------------------------------ */
/*  Output type wrapping (for object types in lists, etc.)             */
/* ------------------------------------------------------------------ */

function wrapOutputType(innerTypeStr: string, gqlType: any): string {
  if (isNonNullType(gqlType)) {
    return wrapOutputTypeInner(innerTypeStr, gqlType.ofType);
  }
  const result = wrapOutputTypeInner(innerTypeStr, gqlType);
  return `${result} | null`;
}

function wrapOutputTypeInner(innerTypeStr: string, gqlType: any): string {
  if (isListType(gqlType)) {
    // Wrap object type in array
    return `Array<${innerTypeStr} | null>`;
  }
  return innerTypeStr;
}

/* ------------------------------------------------------------------ */
/*  Input type resolution                                              */
/* ------------------------------------------------------------------ */

function resolveInputGraphQLType(ctx: GeneratorContext, gqlType: any): string {
  if (isNonNullType(gqlType)) {
    return resolveInputGraphQLTypeInner(ctx, gqlType.ofType);
  }
  return resolveInputGraphQLTypeInner(ctx, gqlType) + ' | null';
}

function resolveInputGraphQLTypeInner(
  ctx: GeneratorContext,
  gqlType: any
): string {
  if (isListType(gqlType)) {
    const inner = resolveInputGraphQLType(ctx, gqlType.ofType);
    return `Array<${inner}>`;
  }
  if (isInputObjectType(gqlType)) {
    return gqlType.name;
  }
  return resolveScalarOrEnumType(ctx, gqlType);
}

function resolveInputTypeNode(
  ctx: GeneratorContext,
  typeNode: TypeNode
): string {
  if (typeNode.kind === Kind.NON_NULL_TYPE) {
    return resolveInputTypeNodeInner(ctx, typeNode.type);
  }
  return resolveInputTypeNodeInner(ctx, typeNode) + ' | null';
}

function resolveInputTypeNodeInner(
  ctx: GeneratorContext,
  typeNode: any
): string {
  if (typeNode.kind === Kind.LIST_TYPE) {
    const inner = resolveInputTypeNode(ctx, typeNode.type);
    return `Array<${inner}>`;
  }
  const typeName = typeNode.name.value;
  const schemaType = ctx.schema.getType(typeName);
  if (schemaType) {
    if (isInputObjectType(schemaType)) return typeName;
    if (isEnumType(schemaType)) return typeName;
    if (isScalarType(schemaType)) {
      const customMapping = ctx.config.scalars?.[typeName];
      if (customMapping) return customMapping;
      return DEFAULT_SCALARS[typeName] ?? 'any';
    }
  }
  return DEFAULT_SCALARS[typeName] ?? 'any';
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function resolveScalarOrEnumType(
  ctx: GeneratorContext,
  namedType: any
): string {
  if (isEnumType(namedType)) {
    return namedType.name;
  }
  if (isScalarType(namedType)) {
    const customMapping = ctx.config.scalars?.[namedType.name];
    if (customMapping) return customMapping;
    return DEFAULT_SCALARS[namedType.name] ?? 'any';
  }
  return 'unknown';
}

function formatObjectType(fields: FieldEntry[]): string {
  if (fields.length === 0) return '{}';
  const lines = fields.map(
    f => `  ${f.key}${f.optional ? '?' : ''}: ${f.typeStr};`
  );
  return `{\n${lines.join('\n')}\n}`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
