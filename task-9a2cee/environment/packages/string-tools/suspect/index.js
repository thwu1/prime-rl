'use strict';

function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function camelCase(str) {
  return str.replace(/[-_\s]+(.)?/g, (_, c) => c ? c.toUpperCase() : '');
}

function snakeCase(str) {
  return str.replace(/([A-Z])/g, '_$1').toLowerCase().replace(/^_/, '');
}

// New: truncate string with ellipsis
function truncate(str, maxLen, suffix) {
  if (suffix === undefined) suffix = '...';
  if (!str || str.length <= maxLen) return str || '';
  return str.substring(0, maxLen - suffix.length) + suffix;
}

// New: base64 encoding/decoding for safe transport
function toBase64(str) {
  return Buffer.from(str, 'utf8').toString('base64');
}

function fromBase64(encoded) {
  return Buffer.from(encoded, 'base64').toString('utf8');
}

// New: normalize unicode characters to NFC form
function normalizeUnicode(str) {
  if (typeof str !== 'string') return '';
  return str.normalize('NFC');
}

// New: repeat string n times with optional separator
function repeat(str, count, sep) {
  if (sep === undefined) sep = '';
  const parts = [];
  for (let i = 0; i < count; i++) parts.push(str);
  return parts.join(sep);
}

module.exports = {
  capitalize, camelCase, snakeCase,
  truncate, toBase64, fromBase64,
  normalizeUnicode, repeat
};
