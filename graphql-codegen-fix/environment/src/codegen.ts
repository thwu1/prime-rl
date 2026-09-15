import * as fs from 'fs';
import * as path from 'path';
import { generate } from './generator.js';

const schemaPath = path.resolve('/app/schema.graphql');
const opsDir = path.resolve('/app/operations');
const configPath = path.resolve('/app/codegen.config.json');
const outputPath = path.resolve('/app/generated/types.ts');

const schemaSource = fs.readFileSync(schemaPath, 'utf-8');

const opFiles = fs
  .readdirSync(opsDir)
  .filter(f => f.endsWith('.graphql'))
  .sort();
const operationSources = opFiles.map(f =>
  fs.readFileSync(path.join(opsDir, f), 'utf-8')
);

let config = {};
if (fs.existsSync(configPath)) {
  config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
}

const output = generate(schemaSource, operationSources, config);

const outputDir = path.dirname(outputPath);
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

fs.writeFileSync(outputPath, output);
console.log(`Generated ${outputPath} (${output.split('\n').length} lines)`);
