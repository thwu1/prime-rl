
import { Parser } from './parser.js';
import { format } from './formatter.js';

async function main() {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk as Buffer);
  }
  const input = Buffer.concat(chunks).toString('utf-8');

  try {
    const { pattern, locale, values } = JSON.parse(input);
    const parser = new Parser(pattern);
    const ast = parser.parse();
    const result = format(ast, locale || 'en', values || {});
    process.stdout.write(result);
  } catch (err: any) {
    process.stderr.write(`ERROR: ${err.message || err}\n`);
    process.exit(1);
  }
}

main();
