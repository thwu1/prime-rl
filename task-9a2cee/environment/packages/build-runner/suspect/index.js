'use strict';
const { execSync } = require('child_process');
const BuildCache = require('./cache');

class BuildRunner {
  constructor(config) {
    if (!config) config = {};
    this.scripts = config.scripts || {};
    this.env = config.env || {};
    this.cwd = config.cwd || process.cwd();
    this.cache = new BuildCache(config.cacheDir);
  }

  run(scriptName, opts) {
    if (!opts) opts = {};
    const script = this.scripts[scriptName];
    if (!script) {
      throw new Error('Unknown script: ' + scriptName);
    }

    // Use cached result if available and not forced
    if (!opts.force && this.cache.isValid(scriptName)) {
      return '[cached]';
    }

    const result = execSync(script, {
      cwd: this.cwd,
      env: Object.assign({}, process.env, this.env),
      encoding: 'utf8',
      timeout: 30000
    });

    return result.trim();
  }

  // Clean build artifacts and invalidate caches
  clean(dir) {
    this.cache.invalidate(dir || this.cwd);
  }

  list() {
    return Object.keys(this.scripts);
  }
}

module.exports = BuildRunner;
