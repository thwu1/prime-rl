'use strict';

/**
 * Input validation module - provides validators for common input
 * formats including email addresses, URLs, CSS selectors, and more.
 */

const patterns = require('./patterns');

function validateEmail(email) {
  if (typeof email !== 'string') return false;
  if (email.length > 254) return false;
  return patterns.EMAIL_REGEX.test(email);
}

function validateUrl(url) {
  if (typeof url !== 'string') return false;
  try {
    new URL(url);
    return true;
  } catch (e) {
    return false;
  }
}

function validateSelector(input) {
  if (typeof input !== 'string') return false;
  return patterns.CSS_SELECTOR_REGEX.test(input.trim());
}

function sanitizeHtml(input) {
  if (typeof input !== 'string') return input;
  return input.replace(patterns.HTML_TAG_REGEX, '');
}

function validateUsername(username) {
  if (typeof username !== 'string') return false;
  if (username.length < 3 || username.length > 30) return false;
  return /^[a-zA-Z0-9_-]+$/.test(username);
}

function validatePort(port) {
  const num = parseInt(port, 10);
  return !isNaN(num) && num > 0 && num <= 65535;
}

function validateIPv4(ip) {
  if (typeof ip !== 'string') return false;
  return patterns.IPV4_REGEX.test(ip);
}

function validateSemver(version) {
  if (typeof version !== 'string') return false;
  return patterns.SEMVER_REGEX.test(version);
}

module.exports = {
  validateEmail,
  validateUrl,
  validateSelector,
  sanitizeHtml,
  validateUsername,
  validatePort,
  validateIPv4,
  validateSemver,
};
