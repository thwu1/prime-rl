// Mitigation: Code Injection — use safeLoad() instead of load()
//
// js-yaml's safeLoad() uses DEFAULT_SAFE_SCHEMA which does NOT include
// the !!js/function, !!js/regexp, or !!js/undefined types.  YAML containing
// these tags is rejected with a parse error, preventing code execution.

'use strict';

const yaml = require('js-yaml');

function safeLoadYaml(content) {
  return yaml.safeLoad(content);
}

// Reset proof marker
delete global.__YAML_MITIGATION_TEST__;

// Attempt the same exploit payload
const payload =
  '{ toString: !<tag:yaml.org,2002:js/function> \'function (){global.__YAML_MITIGATION_TEST__=true;return "pwned";}\' } : 1';

try {
  safeLoadYaml(payload);
} catch (_) {
  // safeLoad should reject !!js/function — this catch is expected
}

if (global.__YAML_MITIGATION_TEST__ !== true) {
  console.log('MITIGATED: code injection prevented by using yaml.safeLoad() which rejects !!js/function');
  process.exit(0);
} else {
  console.error('MITIGATION FAILED — code was executed despite safeLoad');
  process.exit(1);
}
