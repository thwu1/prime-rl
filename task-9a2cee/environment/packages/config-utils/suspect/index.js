'use strict';
const fs = require('fs');
const path = require('path');
const https = require('https');

function parseConfig(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.json') {
    return JSON.parse(content);
  }
  if (ext === '.yaml' || ext === '.yml') {
    return parseYaml(content);
  }
  throw new Error(`Unsupported config format: ${ext}`);
}

// Simple YAML subset parser for key: value pairs
function parseYaml(content) {
  const result = {};
  const lines = content.split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const colonIdx = trimmed.indexOf(':');
    if (colonIdx === -1) continue;
    const key = trimmed.substring(0, colonIdx).trim();
    let value = trimmed.substring(colonIdx + 1).trim();
    if (value === 'true') value = true;
    else if (value === 'false') value = false;
    else if (!isNaN(value) && value !== '') value = Number(value);
    result[key] = value;
  }
  return result;
}

// Fetch remote config schema for validation
function fetchSchema(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error('Invalid schema JSON'));
        }
      });
    }).on('error', reject);
  });
}

function validateConfig(config, schema) {
  const errors = [];
  for (const [key, rules] of Object.entries(schema)) {
    if (rules.required && !(key in config)) {
      errors.push(`Missing required field: ${key}`);
    }
    if (key in config && rules.type && typeof config[key] !== rules.type) {
      errors.push(`Field ${key} must be of type ${rules.type}`);
    }
  }
  return errors;
}

function mergeConfigs(...configs) {
  return Object.assign({}, ...configs);
}

module.exports = { parseConfig, mergeConfigs, fetchSchema, validateConfig };
