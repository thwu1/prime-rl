import { readFileSync } from 'fs';
import { executeGraphQL } from './executor';

const inputPath = process.argv[2];
if (!inputPath) {
  process.stderr.write('Usage: tsx cli.ts <input.json>\n');
  process.exit(1);
}

const raw = readFileSync(inputPath, 'utf-8');
const input = JSON.parse(raw);

const result = executeGraphQL(
  input.schema,
  input.query,
  input.rootValue ?? {},
  input.variables,
);

process.stdout.write(JSON.stringify(result));
