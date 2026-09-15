'use strict';

// Regex patterns for input validation

// Email validation - RFC 5322 inspired pattern
// Uses a capturing group + backreference for optional local-part repeat check
const EMAIL_REGEX = /^(([a-zA-Z0-9]+)[._+\-]?)*\2?@([a-zA-Z0-9]+[\.\-]?)*[a-zA-Z0-9]+\.[a-zA-Z]{2,}$/;

// CSS nth-child selector validation
const CSS_SELECTOR_REGEX = /^\s*([+-]?\d*n)?\s*([+-]\s*\d+)?\s*$/;

// HTML tag matching for sanitization
const HTML_TAG_REGEX = /<[^>]*>/g;

// IPv4 address validation
const IPV4_REGEX = /^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$/;

// Semantic version matching
const SEMVER_REGEX = /^v?(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?(?:\+([a-zA-Z0-9.]+))?$/;

module.exports = {
  EMAIL_REGEX,
  CSS_SELECTOR_REGEX,
  HTML_TAG_REGEX,
  IPV4_REGEX,
  SEMVER_REGEX,
};
