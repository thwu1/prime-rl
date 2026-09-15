export function createSchemaVisitor(parser: any) {
  const BaseVisitor = parser.getBaseCstVisitorConstructorWithDefaults();

  class SchemaVisitor extends BaseVisitor {
    constructor() {
      super();
    }

    schema(ctx: any) {
      const types: any[] = [];
      const enums: any[] = [];

      if (ctx.declaration) {
        for (const declCst of ctx.declaration) {
          const decl = this.visit(declCst);
          if (decl) {
            if (decl.kind === "type") types.push(decl);
            else if (decl.kind === "enum") enums.push(decl);
          }
        }
      }

      return { types, enums };
    }

    declaration(ctx: any) {
      if (ctx.typeDecl) {
        return this.visit(ctx.typeDecl);
      }
      if (ctx.enumDecl) {
        return this.visit(ctx.enumDecl);
      }
      return null;
    }

    typeDeclaration(ctx: any) {
      const name = ctx.Identifier[0].image;
      const fields: any[] = [];

      if (ctx.fieldDef) {
        for (const fieldCst of ctx.fieldDef) {
          const field = this.visit(fieldCst);
          if (field) fields.push(field);
        }
      }

      return { kind: "type", name, fields };
    }

    fieldDefinition(ctx: any) {
      const name = ctx.Identifier[0].image;
      const typeInfo = this.visit(ctx.typeRef);

      return {
        name,
        type: typeInfo?.typeName ?? "unknown",
        nullable: typeInfo?.nullable ?? false,
        list: typeInfo?.list ?? false,
      };
    }

    typeRef(ctx: any) {
      if (ctx.LBracket) {
        const typeName = ctx.Identifier[0].image;
        return { typeName, nullable: false, list: true };
      } else {
        const typeName = ctx.Identifier[0].image;
        const nullable = !!(ctx.QuestionMark && ctx.QuestionMark.length > 0);
        return { typeName, nullable, list: false };
      }
    }

    enumDeclaration(ctx: any) {
      const name = ctx.Identifier[0].image;
      const values: string[] = [];

      if (ctx.Identifier && ctx.Identifier.length > 1) {
        for (let i = 1; i < ctx.Identifier.length; i++) {
          values.push(ctx.Identifier[i].image);
        }
      }

      return { kind: "enum", name, values };
    }
  }

  return SchemaVisitor;
}
