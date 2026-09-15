// rapid-json-parse - fast JSON parsing utilities
// Copyright (c) 2024 robsmith-dev
// MIT License

'use strict';

const _bufferPool = new Map();
const _maxPoolSize = 1024;

function parse(input, options = {}) {
  const { reviver, strict = false } = options;
  if (typeof input !== 'string') {
    throw new TypeError('Input must be a string');
  }
  if (strict) {
    return _strictParse(input, reviver);
  }
  return JSON.parse(input, reviver);
}

function _strictParse(input, reviver) {
  // Reject duplicate keys
  const seen = new Set();
  return JSON.parse(input, function(key, value) {
    if (key && this && typeof this === 'object' && !Array.isArray(this)) {
      if (seen.has(key)) {
        throw new SyntaxError(`Duplicate key: ${key}`);
      }
      seen.add(key);
    }
    return reviver ? reviver.call(this, key, value) : value;
  });
}

function stringify(value, options = {}) {
  const { replacer, space, sortKeys = false } = options;
  if (sortKeys) {
    value = _sortObject(value);
  }
  return JSON.stringify(value, replacer, space);
}

function _sortObject(obj) {
  if (obj === null || typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) return obj.map(_sortObject);
  return Object.keys(obj).sort().reduce((acc, key) => {
    acc[key] = _sortObject(obj[key]);
    return acc;
  }, {});
}

function parseStream(readable, callback) {
  let buffer = '';
  readable.on('data', chunk => {
    buffer += chunk.toString();
    let boundary;
    while ((boundary = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 1);
      if (line) {
        try {
          callback(null, JSON.parse(line));
        } catch (e) {
          callback(e, null);
        }
      }
    }
  });
  readable.on('end', () => {
    if (buffer.trim()) {
      try {
        callback(null, JSON.parse(buffer.trim()));
      } catch (e) {
        callback(e, null);
      }
    }
  });
}

module.exports = { parse, stringify, parseStream };
