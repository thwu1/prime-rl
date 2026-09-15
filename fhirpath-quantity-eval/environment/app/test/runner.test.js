'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { parse } = require('../src/parser');
const { evaluate, formatResult } = require('../src/evaluator');

function evalExpression(expr) {
  try {
    const ast = parse(expr);
    const result = evaluate(ast);
    return formatResult(result);
  } catch (e) {
    return `ERROR: ${e.message}`;
  }
}

const casesDir = path.join(__dirname, 'cases');
const caseFiles = fs.readdirSync(casesDir).filter(f => f.endsWith('.yaml'));

for (const file of caseFiles) {
  const content = fs.readFileSync(path.join(casesDir, file), 'utf8');
  const data = yaml.load(content);
  const suiteName = data.suite || path.basename(file, '.yaml');

  describe(suiteName, () => {
    for (const tc of data.tests) {
      test(tc.name || tc.expression, () => {
        const actual = evalExpression(tc.expression);
        expect(actual).toBe(tc.expected);
      });
    }
  });
}
