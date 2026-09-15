// Mitigation: ReDoS — validate input length before calling parse()
//
// The catastrophic backtracking in nth-check's regex is only exploitable
// with very long inputs.  Rejecting inputs longer than a reasonable limit
// (256 characters is far more than any legitimate CSS nth-check formula)
// eliminates the attack surface with zero false positives.

'use strict';

const nthCheck = require('nth-check');

const MAX_FORMULA_LENGTH = 256;

function safeParse(formula) {
  if (typeof formula !== 'string' || formula.length > MAX_FORMULA_LENGTH) {
    throw new Error('nth-check formula rejected: invalid or exceeds ' + MAX_FORMULA_LENGTH + ' chars');
  }
  return nthCheck.parse(formula);
}

// Attempt the same exploit payload
const payload = '2n' + ' '.repeat(25000) + '!';
const start = Date.now();
try {
  safeParse(payload);
  console.error('MITIGATION FAILED — long input was not rejected');
  process.exit(1);
} catch (e) {
  const elapsed = Date.now() - start;
  if (elapsed < 100) {
    console.log('MITIGATED: ReDoS prevented by input length validation (' + elapsed + 'ms, rejected at boundary)');
    process.exit(0);
  } else {
    console.error('MITIGATION FAILED — rejection took too long (' + elapsed + 'ms)');
    process.exit(1);
  }
}
