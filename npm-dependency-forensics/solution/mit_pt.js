// Mitigation: Path Traversal — reject SymbolicLink entries during extraction
//
// Pass a filter callback to tar.x() that drops all SymbolicLink entries.
// This prevents the directory-cache-poisoning attack entirely because the
// symlink that would replace the cached directory never gets created.

'use strict';

const tar  = require('tar');
const fs   = require('fs');
const { execSync } = require('child_process');

const PID      = process.pid;
const EXTRACT  = '/tmp/tar_mit_extract_' + PID;
const TARGET   = '/tmp/tar_mit_target_' + PID;
const TAR_PATH = '/tmp/mit_' + PID + '.tar';

function cleanup() {
  try { execSync('rm -rf ' + EXTRACT + ' ' + TARGET + ' ' + TAR_PATH); } catch (_) {}
}

cleanup();
fs.mkdirSync(EXTRACT, { recursive: true });
fs.mkdirSync(TARGET,  { recursive: true });

// Build the same malicious tar as the exploit
execSync(`python3 /app/exploits/create_tar.py "${TAR_PATH}" "${TARGET}"`);

// Extract WITH symlink filter (mitigation)
try {
  tar.x({
    file: TAR_PATH,
    cwd: EXTRACT,
    sync: true,
    filter: function (_path, entry) {
      if (entry.type === 'SymbolicLink') {
        return false;   // reject symlinks
      }
      return true;
    },
  });
} catch (_) {}

const proofFile = TARGET + '/pwned.txt';
if (!fs.existsSync(proofFile)) {
  console.log('MITIGATED: path traversal prevented by rejecting SymbolicLink entries in tar filter');
  cleanup();
  process.exit(0);
} else {
  console.error('MITIGATION FAILED — file escaped through symlink');
  cleanup();
  process.exit(1);
}
