export interface Diagnostic {
  severity: "error" | "warning";
  message: string;
}

interface TypeDef {
  name: string;
  fields: { name: string; type: string; nullable: boolean; list: boolean }[];
}

interface EnumDef {
  name: string;
  values: string[];
}

interface AST {
  types: TypeDef[];
  enums: EnumDef[];
}

export function analyze(ast: AST): Diagnostic[] {
  const diagnostics: Diagnostic[] = [];

  checkDuplicateNames(ast, diagnostics);
  checkUndefinedTypes(ast, diagnostics);
  checkDuplicateFields(ast, diagnostics);
  checkDuplicateEnumValues(ast, diagnostics);
  checkRequiredCycles(ast, diagnostics);

  return diagnostics;
}

function checkDuplicateNames(ast: AST, diagnostics: Diagnostic[]) {
  const seen = new Map<string, string>();
  for (const t of ast.types) {
    const key = t.name.toLowerCase();
    if (seen.has(key)) {
      diagnostics.push({
        severity: "error",
        message: `Duplicate definition: '${t.name}' conflicts with '${seen.get(key)}'`,
      });
    }
    seen.set(key, t.name);
  }
  for (const e of ast.enums) {
    const key = e.name.toLowerCase();
    if (seen.has(key)) {
      diagnostics.push({
        severity: "error",
        message: `Duplicate definition: '${e.name}' conflicts with '${seen.get(key)}'`,
      });
    }
    seen.set(key, e.name);
  }
}

function checkUndefinedTypes(ast: AST, diagnostics: Diagnostic[]) {
  const builtinTypes = new Set(["Int", "String", "Boolean", "Float", "ID"]);
  const definedNames = new Set<string>();

  for (const t of ast.types) {
    definedNames.add(t.name);
  }

  for (const t of ast.types) {
    for (const f of t.fields) {
      if (!builtinTypes.has(f.type) && !definedNames.has(f.type)) {
        diagnostics.push({
          severity: "error",
          message: `Undefined type '${f.type}' in field '${t.name}.${f.name}'`,
        });
      }
    }
  }
}

function checkDuplicateFields(ast: AST, diagnostics: Diagnostic[]) {
  for (const t of ast.types) {
    const fieldNames = new Set<string>();
    for (const f of t.fields) {
      if (fieldNames.has(f.name)) {
        diagnostics.push({
          severity: "error",
          message: `Duplicate field '${f.name}' in type '${t.name}'`,
        });
      }
      fieldNames.add(f.name);
    }
  }
}

function checkDuplicateEnumValues(ast: AST, diagnostics: Diagnostic[]) {
  for (const e of ast.enums) {
    const valueSet = new Set<string>();
    for (const v of e.values) {
      if (valueSet.has(v)) {
        diagnostics.push({
          severity: "error",
          message: `Duplicate value '${v}' in enum '${e.name}'`,
        });
      }
      valueSet.add(v);
    }
  }
}

function checkRequiredCycles(ast: AST, diagnostics: Diagnostic[]) {
  for (const t of ast.types) {
    for (const f of t.fields) {
      if (f.type === t.name && !f.nullable && !f.list) {
        diagnostics.push({
          severity: "error",
          message: `Required cycle: type '${t.name}' has non-nullable non-list field '${f.name}' referencing itself`,
        });
      }
    }
  }
}
