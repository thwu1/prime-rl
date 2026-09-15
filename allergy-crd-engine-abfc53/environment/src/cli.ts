
import { processPanel } from './engine';
import { PatientPanel } from './types';
import * as fs from 'fs';

const inputPath = process.argv[2];
if (!inputPath) {
  console.error('Usage: node dist/cli.js <input.json>');
  process.exit(1);
}

const inputData = fs.readFileSync(inputPath, 'utf-8');
const panel: PatientPanel = JSON.parse(inputData);
const report = processPanel(panel);
console.log(JSON.stringify(report, null, 2));
