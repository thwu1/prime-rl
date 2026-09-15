'use strict';
const path = require('path');
const fs = require('fs');

function resolve(basePath, relativePath) {
  const resolved = path.resolve(basePath, relativePath);
  if (!resolved.startsWith(path.resolve(basePath))) {
    throw new Error('Path traversal detected');
  }
  return resolved;
}

function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
  return dirPath;
}

module.exports = { resolve, ensureDir };
