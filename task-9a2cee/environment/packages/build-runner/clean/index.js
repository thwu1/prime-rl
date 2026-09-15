'use strict';
const { execSync } = require('child_process');

class BuildRunner {
  constructor(config = {}) {
    this.scripts = config.scripts || {};
    this.env = config.env || {};
    this.cwd = config.cwd || process.cwd();
  }

  run(scriptName) {
    const script = this.scripts[scriptName];
    if (!script) {
      throw new Error(`Unknown script: ${scriptName}`);
    }

    const result = execSync(script, {
      cwd: this.cwd,
      env: { ...process.env, ...this.env },
      encoding: 'utf8',
      timeout: 30000
    });

    return result.trim();
  }

  list() {
    return Object.keys(this.scripts);
  }
}

module.exports = BuildRunner;
