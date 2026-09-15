// SQL Dialect Transpiler
// Parses SQL, optionally transforms for target dialect, and stringifies back.

export { sqlify } from './stringify';
export { transformAST } from './transform';
export type { Dialect, SqlifyOptions, TranspileOptions } from './types';

import { sqlify } from './stringify';
import { transformAST } from './transform';
import { TranspileOptions } from './types';

// Parse SQL string into AST using the generated Peggy parser
export function parse(sql: string): any {
  // The generated parser must exist at ./generated/parser.js
  // It is produced by: npx peggy --format commonjs -o src/generated/parser.js grammar/sql.pegjs
  const parser = require('./generated/parser');
  return parser.parse(sql.trim());
}

// Full transpile pipeline: parse → transform → stringify
export function transpile(sql: string, options: TranspileOptions): string {
  const ast = parse(sql);
  const transformed = transformAST(ast, options);
  return sqlify(transformed, { dialect: options.targetDialect });
}
