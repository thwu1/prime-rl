import boolean from './src/index';


const opCode = parseInt(process.argv[2]);
const subject = JSON.parse(process.argv[3]);
const clipping = JSON.parse(process.argv[4]);

const result = boolean(subject, clipping, opCode);
if (result === null || (Array.isArray(result) && result.length === 0)) {
  process.stdout.write("null");
} else {
  process.stdout.write(JSON.stringify(result));
}
