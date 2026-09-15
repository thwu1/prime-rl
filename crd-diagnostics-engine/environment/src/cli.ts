
import { processPanel } from './crd-engine';
import { PatientPanel } from './types';

let input = '';
process.stdin.setEncoding('utf-8');
process.stdin.on('data', (chunk: string) => { input += chunk; });
process.stdin.on('end', () => {
  try {
    const panel: PatientPanel = JSON.parse(input);
    const report = processPanel(panel);
    process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  } catch (err: any) {
    process.stderr.write('Error: ' + err.message + '\n');
    process.exit(1);
  }
});
