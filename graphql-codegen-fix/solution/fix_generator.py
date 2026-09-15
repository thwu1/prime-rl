
"""
Fix the 6 bugs in /app/src/generator.ts:
1. Fragment spread lookup uses wrong key (appends 'Fragment')
2. Polymorphic selection sets don't produce discriminated unions
3. Field aliases are ignored
4. @skip/@include directives don't make fields optional
5. @oneOf input types aren't handled specially
6. List inner-item nullability is always nullable
"""

import re

SRC = '/app/src/generator.ts'

with open(SRC, 'r') as f:
    code = f.read()

# =====================================================================
# Bug 1: Fragment spread lookup appends 'Fragment' to the key, but the
# fragment map stores fragments by their GraphQL name.
# Fix: remove the + 'Fragment' suffix.
# =====================================================================
code = code.replace(
    "const fragName = selection.name.value + 'Fragment';",
    "const fragName = selection.name.value;",
)

# =====================================================================
# Bug 3: Field names don't check for aliases.
# Fix: use alias if present, otherwise field name.
# =====================================================================
code = code.replace(
    "// Get the output key for this field\n        const fieldName = selection.name.value;",
    "// Get the output key for this field (prefer alias if present)\n        const fieldName = (selection as any).alias?.value ?? selection.name.value;",
)

# =====================================================================
# Bug 4: Conditional directives @skip/@include are ignored.
# Fix: check for these directives and mark the field as optional.
# =====================================================================
code = code.replace(
    "// Determine if field is optional\n        const optional = false;",
    "// Determine if field is optional (check @skip/@include directives)\n"
    "        const optional = ((selection as any).directives ?? []).some(\n"
    "          (d: any) => d.name.value === 'skip' || d.name.value === 'include'\n"
    "        );",
)

# =====================================================================
# Bug 5: @oneOf input types should generate exclusive union types.
# Fix: add @oneOf detection in emitInputType.
# =====================================================================
old_emit_input = '''function emitInputType(
  ctx: GeneratorContext,
  inputType: GraphQLInputObjectType
): string {
  const fields = inputType.getFields();
  const fieldStrs = Object.values(fields).map(f => {
    const tsType = resolveInputGraphQLType(ctx, f.type);
    const isRequired = isNonNullType(f.type);
    return `  ${f.name}${isRequired ? '' : '?'}: ${tsType};`;
  });
  return `export type ${inputType.name} = {\\n${fieldStrs.join('\\n')}\\n};`;
}'''

new_emit_input = '''function emitInputType(
  ctx: GeneratorContext,
  inputType: GraphQLInputObjectType
): string {
  // Check if this is a @oneOf input type
  const isOneOf = (inputType as any).isOneOf === true ||
    inputType.astNode?.directives?.some((d: any) => d.name.value === 'oneOf') === true;

  const fields = inputType.getFields();
  const fieldNames = Object.keys(fields);

  if (isOneOf) {
    // Generate a union of single-field objects with 'never' for other fields
    const branches = fieldNames.map(activeField => {
      const parts = fieldNames.map(fn => {
        if (fn === activeField) {
          const tsType = resolveInputGraphQLTypeInner(ctx, getNullableType(fields[fn].type));
          return `  ${fn}: ${tsType};`;
        } else {
          return `  ${fn}?: never;`;
        }
      });
      return `{\\n${parts.join('\\n')}\\n}`;
    });
    return `export type ${inputType.name} =\\n  | ${branches.join('\\n  | ')};`;
  }

  const fieldStrs = Object.values(fields).map(f => {
    const tsType = resolveInputGraphQLType(ctx, f.type);
    const isRequired = isNonNullType(f.type);
    return `  ${f.name}${isRequired ? '' : '?'}: ${tsType};`;
  });
  return `export type ${inputType.name} = {\\n${fieldStrs.join('\\n')}\\n};`;
}'''

code = code.replace(old_emit_input, new_emit_input)

# We also need to add the getNullableType import
code = code.replace(
    "  getNamedType,",
    "  getNamedType,\n  getNullableType,",
)

# And make resolveInputGraphQLTypeInner accessible (it's already defined, just used internally)
# We also need to export resolveInputGraphQLTypeInner - but since it's in the same file,
# it's already accessible. No change needed there.

# =====================================================================
# Bug 6a: resolveLeafOutputTypeInner always treats list inner items as
# nullable. Fix: check if inner type is NonNull.
# =====================================================================
old_leaf_list = '''  if (isListType(gqlType)) {
    // Resolve inner type for list items
    const innerNamedType = getNamedType(gqlType);
    const innerTsType = resolveScalarOrEnumType(ctx, innerNamedType as any);
    const result = `Array<${innerTsType} | null>`;
    return nullable ? `${result} | null` : result;
  }'''

new_leaf_list = '''  if (isListType(gqlType)) {
    // Resolve inner type for list items, respecting NonNull wrappers
    const innerType = gqlType.ofType;
    const isInnerNonNull = isNonNullType(innerType);
    const innerNamedType = isInnerNonNull ? (innerType as any).ofType : innerType;
    const innerTsType = resolveScalarOrEnumType(ctx, innerNamedType as any);
    const itemType = isInnerNonNull ? innerTsType : `${innerTsType} | null`;
    const result = `Array<${itemType}>`;
    return nullable ? `${result} | null` : result;
  }'''

code = code.replace(old_leaf_list, new_leaf_list)

# =====================================================================
# Bug 6b: wrapOutputTypeInner always treats list object items as nullable.
# Fix: check if inner type is NonNull.
# =====================================================================
old_wrap_inner = '''function wrapOutputTypeInner(innerTypeStr: string, gqlType: any): string {
  if (isListType(gqlType)) {
    // Wrap object type in array
    return `Array<${innerTypeStr} | null>`;
  }
  return innerTypeStr;
}'''

new_wrap_inner = '''function wrapOutputTypeInner(innerTypeStr: string, gqlType: any): string {
  if (isListType(gqlType)) {
    // Wrap object type in array, respecting inner NonNull
    const isInnerNonNull = isNonNullType(gqlType.ofType);
    if (isInnerNonNull) {
      return `Array<${innerTypeStr}>`;
    }
    return `Array<${innerTypeStr} | null>`;
  }
  return innerTypeStr;
}'''

code = code.replace(old_wrap_inner, new_wrap_inner)

# =====================================================================
# Bug 2: resolvePolymorphicSelectionSet merges all inline fragment fields
# into a flat object instead of creating a discriminated union.
# Fix: create branches with __typename discriminator.
# =====================================================================
old_poly = '''function resolvePolymorphicSelectionSet(
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
}'''

new_poly = '''function resolvePolymorphicSelectionSet(
  ctx: GeneratorContext,
  selectionSet: SelectionSetNode,
  parentType: GraphQLUnionType | GraphQLInterfaceType
): string {
  // Collect shared fields (fields directly selected on an interface)
  const sharedFields: FieldEntry[] = [];
  for (const selection of selectionSet.selections) {
    if (selection.kind === Kind.FIELD && isInterfaceType(parentType)) {
      const fieldDef = parentType.getFields()[selection.name.value];
      if (fieldDef) {
        const fieldName = (selection as any).alias?.value ?? selection.name.value;
        const hasCondDir = ((selection as any).directives ?? []).some(
          (d: any) => d.name.value === 'skip' || d.name.value === 'include'
        );
        if (selection.selectionSet) {
          const namedType = getNamedType(fieldDef.type);
          const innerFields = resolveSelectionSet(
            ctx,
            selection.selectionSet,
            namedType as GraphQLObjectType
          );
          const innerTypeStr = formatObjectType(innerFields);
          const wrappedType = wrapOutputType(innerTypeStr, fieldDef.type);
          sharedFields.push({
            key: fieldName,
            typeStr: wrappedType,
            optional: hasCondDir,
          });
        } else {
          const tsType = resolveLeafOutputType(ctx, fieldDef.type);
          sharedFields.push({ key: fieldName, typeStr: tsType, optional: hasCondDir });
        }
      }
    }
  }

  // Collect inline fragment branches and create a discriminated union
  const branches: string[] = [];
  for (const selection of selectionSet.selections) {
    if (selection.kind === Kind.INLINE_FRAGMENT && selection.typeCondition) {
      const typeName = selection.typeCondition.name.value;
      const targetType = ctx.schema.getType(typeName) as GraphQLObjectType;
      const branchFields = resolveSelectionSet(
        ctx,
        selection.selectionSet,
        targetType
      );
      const allBranchFields: FieldEntry[] = [
        { key: '__typename', typeStr: `'${typeName}'`, optional: false },
        ...sharedFields,
        ...branchFields,
      ];
      branches.push(formatObjectType(allBranchFields));
    }
  }

  if (branches.length === 0) {
    return formatObjectType(sharedFields);
  }

  return branches.join(' | ');
}'''

code = code.replace(old_poly, new_poly)

with open(SRC, 'w') as f:
    f.write(code)

print('All 6 bugs fixed in generator.ts')
