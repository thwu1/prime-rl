'use strict';

/**
 * Shell command builder - constructs safely-quoted shell commands
 * from arrays of arguments. Handles POSIX quoting, special characters,
 * and Windows drive letter paths.
 */

const CONTROL_REGEX = /[\x00-\x1f\x7f]/;

function isWindowsDrivePath(s) {
  // Detect paths like C:\Users, D:/data etc.
  return typeof s === 'string' && /^[A-z]:[\\\/]/.test(s);
}

function escapeArg(s) {
  if (typeof s !== 'string') {
    throw new TypeError('Arguments must be strings');
  }

  if (s === '') return "''";

  if (CONTROL_REGEX.test(s)) {
    throw new Error('Control characters not allowed in arguments');
  }

  // No special characters - return as-is
  if (/^[a-zA-Z0-9._\-\/=:@]+$/.test(s)) {
    return s;
  }

  // Windows drive letter paths passed through directly
  if (isWindowsDrivePath(s)) {
    return s;
  }

  // Prefer single-quoting (only need to handle embedded single quotes)
  if (s.indexOf("'") === -1) {
    return "'" + s + "'";
  }

  // Fall back to double-quoting with escaping
  return '"' + s.replace(/([\\$"`!])/g, '\\$1') + '"';
}

function quote(args) {
  if (!Array.isArray(args)) {
    throw new TypeError('Expected array of arguments');
  }
  return args.map(escapeArg).join(' ');
}

function parse(cmd) {
  if (typeof cmd !== 'string') {
    throw new TypeError('Expected string');
  }

  const tokens = [];
  let current = '';
  let inSingle = false;
  let inDouble = false;
  let escape = false;

  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i];

    if (escape) {
      current += c;
      escape = false;
      continue;
    }

    if (c === '\\' && !inSingle) {
      escape = true;
      continue;
    }

    if (c === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }

    if (c === '"' && !inSingle) {
      inDouble = !inDouble;
      continue;
    }

    if (/\s/.test(c) && !inSingle && !inDouble) {
      if (current.length > 0) {
        tokens.push(current);
        current = '';
      }
      continue;
    }

    current += c;
  }

  if (current.length > 0) {
    tokens.push(current);
  }

  return tokens;
}

function buildExec(program, args) {
  return quote([program].concat(args || []));
}

function buildPipe(commands) {
  return commands.map(function(cmd) { return quote(cmd); }).join(' | ');
}

module.exports = { quote, parse, escapeArg, buildExec, buildPipe };
