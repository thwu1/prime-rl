// Mitigation: Prototype Pollution — sanitize keys before unflatten
//
// Filter out any flattened key containing "__proto__" or "constructor.prototype"
// before passing to unflatten().  This prevents the function from navigating
// into Object.prototype.

'use strict';

const { unflatten } = require('flat');

function safeUnflatten(obj) {
  const clean = {};
  for (const key of Object.keys(obj)) {
    if (key.includes('__proto__') || key.includes('constructor.prototype')) {
      continue;  // drop dangerous keys
    }
    clean[key] = obj[key];
  }
  return unflatten(clean);
}

// Attempt the same exploit payload
const malicious = {
  '__proto__.isAdmin': 'true',
  'user.name': 'alice',
  'user.role': 'viewer',
};
const result = safeUnflatten(malicious);

const probe = {};
if (probe.isAdmin !== 'true') {
  console.log('MITIGATED: prototype pollution prevented by filtering __proto__ keys from unflatten input');
  process.exit(0);
} else {
  console.error('MITIGATION FAILED — prototype was polluted');
  process.exit(1);
}
