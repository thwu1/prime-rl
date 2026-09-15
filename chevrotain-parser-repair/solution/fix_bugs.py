#!/usr/bin/env python3
"""
Fix all bugs across the Chevrotain-based schema parser:
  - tokens.ts: token ordering, longer_alt, missing QuestionMark
  - parser.ts: declaration OR, CONSUME collision, recovery override
  - visitor.ts: method name mismatches
  - analyzer.ts: case-insensitive duplicate check, missing enum names,
                 direct-only cycle detection -> full DFS
  - index.ts: integrate analyzer
"""
import re


def fix_tokens():
    with open("/app/src/tokens.ts") as f:
        content = f.read()

    # Add longer_alt to TypeKeyword
    content = content.replace(
        'export const TypeKeyword = createToken({\n'
        '  name: "TypeKeyword",\n'
        '  pattern: /type/,\n'
        '});',
        'export const TypeKeyword = createToken({\n'
        '  name: "TypeKeyword",\n'
        '  pattern: /type/,\n'
        '  longer_alt: Identifier,\n'
        '});',
    )

    # Add longer_alt to EnumKeyword
    content = content.replace(
        'export const EnumKeyword = createToken({\n'
        '  name: "EnumKeyword",\n'
        '  pattern: /enum/,\n'
        '});',
        'export const EnumKeyword = createToken({\n'
        '  name: "EnumKeyword",\n'
        '  pattern: /enum/,\n'
        '  longer_alt: Identifier,\n'
        '});',
    )

    # Rebuild allTokens with correct ordering and QuestionMark included
    old_block = re.search(r"export const allTokens = \[[\s\S]*?\];", content)
    if not old_block:
        raise RuntimeError("Could not locate allTokens")

    new_block = (
        "export const allTokens = [\n"
        "  WhiteSpace,\n"
        "  LineComment,\n"
        "  LCurly,\n"
        "  RCurly,\n"
        "  LBracket,\n"
        "  RBracket,\n"
        "  Colon,\n"
        "  SemiColon,\n"
        "  Comma,\n"
        "  QuestionMark,\n"
        "  TypeKeyword,\n"
        "  EnumKeyword,\n"
        "  Identifier,\n"
        "];"
    )
    content = content[: old_block.start()] + new_block + content[old_block.end():]

    with open("/app/src/tokens.ts", "w") as f:
        f.write(content)


def fix_parser():
    with open("/app/src/parser.ts") as f:
        content = f.read()

    # Fix declaration: second ALT should be enumDecl
    content = content.replace(
        "      { ALT: () => this.SUBRULE(this.typeDecl) },\n"
        "      { ALT: () => this.SUBRULE(this.typeDecl) },",
        "      { ALT: () => this.SUBRULE(this.typeDecl) },\n"
        "      { ALT: () => this.SUBRULE(this.enumDecl) },",
    )

    # Fix CONSUME collision in typeRef: second CONSUME(Identifier) -> CONSUME2
    content = content.replace(
        "          this.CONSUME(Identifier);\n"
        "          this.OPTION(() => {",
        "          this.CONSUME2(Identifier);\n"
        "          this.OPTION(() => {",
    )

    # Remove canTokenTypeBeInsertedInRecovery override
    old_method = (
        "\n"
        "  canTokenTypeBeInsertedInRecovery(tokType: any): boolean {\n"
        "    if (tokType === SemiColon) {\n"
        "      return false;\n"
        "    }\n"
        "    return true;\n"
        "  }"
    )
    content = content.replace(old_method, "")

    with open("/app/src/parser.ts", "w") as f:
        f.write(content)


def fix_visitor():
    with open("/app/src/visitor.ts") as f:
        content = f.read()

    content = content.replace("typeDeclaration(ctx", "typeDecl(ctx")
    content = content.replace("fieldDefinition(ctx", "fieldDef(ctx")
    content = content.replace("enumDeclaration(ctx", "enumDecl(ctx")

    with open("/app/src/visitor.ts", "w") as f:
        f.write(content)


def fix_analyzer():
    """Rewrite analyzer.ts with correct logic."""
    new_content = '''\
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
    if (seen.has(t.name)) {
      diagnostics.push({
        severity: "error",
        message: `Duplicate definition: '${t.name}' conflicts with '${seen.get(t.name)}'`,
      });
    }
    seen.set(t.name, "type");
  }
  for (const e of ast.enums) {
    if (seen.has(e.name)) {
      diagnostics.push({
        severity: "error",
        message: `Duplicate definition: '${e.name}'`,
      });
    }
    seen.set(e.name, "enum");
  }
}

function checkUndefinedTypes(ast: AST, diagnostics: Diagnostic[]) {
  const builtinTypes = new Set(["Int", "String", "Boolean", "Float", "ID"]);
  const definedNames = new Set<string>();

  for (const t of ast.types) {
    definedNames.add(t.name);
  }
  for (const e of ast.enums) {
    definedNames.add(e.name);
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
  const typeMap = new Map<string, TypeDef>();
  for (const t of ast.types) {
    typeMap.set(t.name, t);
  }

  // Build adjacency: only non-nullable, non-list edges to other known types
  const edges = new Map<string, string[]>();
  for (const t of ast.types) {
    const targets: string[] = [];
    for (const f of t.fields) {
      if (!f.nullable && !f.list && typeMap.has(f.type)) {
        targets.push(f.type);
      }
    }
    edges.set(t.name, targets);
  }

  // DFS cycle detection
  const WHITE = 0, GRAY = 1, BLACK = 2;
  const color = new Map<string, number>();
  for (const name of typeMap.keys()) {
    color.set(name, WHITE);
  }
  const reported = new Set<string>();

  function dfs(node: string, path: string[]) {
    color.set(node, GRAY);
    path.push(node);
    for (const next of edges.get(node) ?? []) {
      if (color.get(next) === GRAY) {
        const idx = path.indexOf(next);
        const cycle = path.slice(idx);
        const key = [...cycle].sort().join(",");
        if (!reported.has(key)) {
          reported.add(key);
          diagnostics.push({
            severity: "error",
            message: `Required cycle: ${cycle.join(" -> ")} -> ${next}`,
          });
        }
      } else if (color.get(next) === WHITE) {
        dfs(next, path);
      }
    }
    path.pop();
    color.set(node, BLACK);
  }

  for (const name of typeMap.keys()) {
    if (color.get(name) === WHITE) {
      dfs(name, []);
    }
  }
}
'''
    with open("/app/src/analyzer.ts", "w") as f:
        f.write(new_content)


def fix_index():
    """Integrate the analyzer into index.ts."""
    new_content = '''\
import { SchemaLexer } from "./tokens.js";
import { SchemaParser } from "./parser.js";
import { createSchemaVisitor } from "./visitor.js";
import { analyze } from "./analyzer.js";
import { readFileSync } from "fs";

function parseSchema(input: string) {
  const parser = new SchemaParser();
  const VisitorClass = createSchemaVisitor(parser);
  const visitor = new VisitorClass();

  const lexResult = SchemaLexer.tokenize(input);
  parser.input = lexResult.tokens;
  const cst = parser.schema();

  let ast = null;
  try {
    ast = visitor.visit(cst);
  } catch {
    // visitor error, return partial result
  }

  const resolvedAst = ast ?? { types: [], enums: [] };
  const diagnostics = analyze(resolvedAst);

  return {
    ast: resolvedAst,
    lexErrors: lexResult.errors.map((e: any) => e.message),
    parseErrors: parser.errors.map((e: any) => e.message),
    diagnostics: diagnostics.map((d: any) => ({
      severity: d.severity,
      message: d.message,
    })),
  };
}

const filePath = process.argv[2];
if (!filePath) {
  console.error("Usage: npx tsx src/index.ts <schema-file>");
  process.exit(1);
}

try {
  const input = readFileSync(filePath, "utf-8");
  const result = parseSchema(input);
  console.log(JSON.stringify(result));
} catch (e: any) {
  console.error(e.message);
  process.exit(1);
}
'''
    with open("/app/src/index.ts", "w") as f:
        f.write(new_content)


if __name__ == "__main__":
    fix_tokens()
    fix_parser()
    fix_visitor()
    fix_analyzer()
    fix_index()
    print("All fixes applied.")
