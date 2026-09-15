/**
 * CLI wrapper – reads a JSON AST from stdin, outputs SQL to stdout.
 *
 * Single mode:  echo '{"type":"select",...}' | npx tsx src/cli.ts
 * Batch mode:   echo '[{...},{...}]' | npx tsx src/cli.ts
 *   → outputs JSON array of { sql, error } objects
 */
import { sqlify } from './index';
import { readFileSync } from 'fs';

try {
  const input = readFileSync('/dev/stdin', 'utf-8').trim();
  if (!input) {
    process.stderr.write('Error: empty input\n');
    process.exit(1);
  }

  const parsed = JSON.parse(input);

  if (Array.isArray(parsed)) {
    const results = parsed.map((ast: any) => {
      try {
        return { sql: sqlify(ast), error: null };
      } catch (e: any) {
        return { sql: null, error: e.message };
      }
    });
    process.stdout.write(JSON.stringify(results));
  } else {
    process.stdout.write(sqlify(parsed));
  }
} catch (e: any) {
  process.stderr.write(`Error: ${e.message}\n`);
  process.exit(1);
}
