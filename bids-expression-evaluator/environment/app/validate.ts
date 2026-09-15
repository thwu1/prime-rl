
import { readFileSync } from 'fs';
import { loadRules, validateAll, FileContext } from './src/rule_engine';

const contextsPath = process.argv[2] || './spec/test_contexts.json';
const rulesPath = './spec/validation_rules.yaml';

const rules = loadRules(rulesPath);
const contexts = JSON.parse(readFileSync(contextsPath, 'utf8')) as FileContext[];
const reports = validateAll(rules, contexts);

console.log(JSON.stringify(reports, null, 2));
