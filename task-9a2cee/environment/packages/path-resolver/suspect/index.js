'use strict';
const path = require('path');
const fs = require('fs');

function resolve(basePath, relativePath) {
  // Fix: normalize separators for cross-platform compatibility
  const normalizedBase = path.resolve(basePath).split(path.sep).join('/');
  const resolved = path.resolve(basePath, relativePath);
  const normalizedResolved = resolved.split(path.sep).join('/');

  if (!normalizedResolved.startsWith(normalizedBase)) {
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

// New: recursively list files matching an optional regex pattern
function listFiles(dir, pattern) {
  const results = [];
  if (!fs.existsSync(dir)) return results;

  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push.apply(results, listFiles(fullPath, pattern));
    } else if (!pattern || entry.name.match(pattern)) {
      results.push(fullPath);
    }
  }
  return results;
}

// New: get relative path between two absolute paths
function relativize(from, to) {
  return path.relative(from, to);
}

module.exports = { resolve, ensureDir, listFiles, relativize };
