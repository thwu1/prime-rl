/**
 * SQL AST Stringifier – main entry point.
 *
 * Converts SQL AST objects into SQL strings.
 *
 * Usage:
 *   import { sqlify } from './index';
 *   const sql = sqlify(ast);
 */
import './init'; // ensure all expression handlers are registered
import { unionToSQL } from './union';

export function sqlify(ast: any): string {
  if (Array.isArray(ast)) {
    return ast
      .map((stmt: any) => {
        const s = stmt.ast || stmt;
        return unionToSQL(s);
      })
      .join(' ; ');
  }
  const s = ast.ast || ast;
  return unionToSQL(s);
}
