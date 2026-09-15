import { SchemaLexer } from "./tokens.js";
import { SchemaParser } from "./parser.js";
import { createSchemaVisitor } from "./visitor.js";
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

  return {
    ast: ast ?? { types: [], enums: [] },
    lexErrors: lexResult.errors.map((e: any) => e.message),
    parseErrors: parser.errors.map((e: any) => e.message),
    diagnostics: [],
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
