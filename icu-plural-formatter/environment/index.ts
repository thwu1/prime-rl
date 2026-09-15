
import { parse } from './parser';
import { format } from './formatter';

const args = process.argv.slice(2);
const message = args[0];
const locale = args[1];
const valuesJson = args[2];

if (!message || !locale) {
  console.error('Usage: node index.js <message> <locale> [valuesJson]');
  process.exit(1);
}

const values: Record<string, any> = valuesJson ? JSON.parse(valuesJson) : {};
const ast = parse(message);
const result = format(ast, locale, values);
console.log(result);
