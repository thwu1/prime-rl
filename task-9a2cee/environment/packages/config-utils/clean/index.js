'use strict';
const fs = require('fs');
const path = require('path');

function parseConfig(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.json') {
    return JSON.parse(content);
  }
  throw new Error(`Unsupported config format: ${ext}`);
}

function mergeConfigs(...configs) {
  return Object.assign({}, ...configs);
}

module.exports = { parseConfig, mergeConfigs };
