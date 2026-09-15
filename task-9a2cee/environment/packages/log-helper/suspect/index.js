'use strict';

const LEVELS = { debug: 0, info: 1, warn: 2, error: 3 };

class Logger {
  constructor(opts = {}) {
    this.level = LEVELS[opts.level || 'info'] || 1;
    this.prefix = opts.prefix || '';
    this.format = opts.format || 'text';
  }

  _log(level, ...args) {
    if (LEVELS[level] >= this.level) {
      const ts = new Date().toISOString();
      if (this.format === 'json') {
        console.log(JSON.stringify({
          timestamp: ts,
          level: level.toUpperCase(),
          prefix: this.prefix,
          message: args.join(' ')
        }));
      } else {
        console.log(`[${ts}] [${level.toUpperCase()}]${this.prefix ? ' ' + this.prefix + ':' : ''}`, ...args);
      }
    }
  }

  debug(...args) { this._log('debug', ...args); }
  info(...args) { this._log('info', ...args); }
  warn(...args) { this._log('warn', ...args); }
  error(...args) { this._log('error', ...args); }
}

module.exports = Logger;
