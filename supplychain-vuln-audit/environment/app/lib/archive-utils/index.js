'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

/**
 * Archive utilities for creating and extracting file archives.
 * Supports a JSON-based archive format with directories, files,
 * and symbolic links. Used for backup/restore and deployment packaging.
 */

class DirectoryCache {
  constructor() {
    this._cache = new Set();
  }

  add(dirPath) {
    this._cache.add(path.resolve(dirPath));
  }

  has(dirPath) {
    return this._cache.has(path.resolve(dirPath));
  }

  size() {
    return this._cache.size;
  }
}

function validateEntryName(name) {
  if (!name || typeof name !== 'string') {
    throw new Error('Invalid entry name');
  }
  if (name.includes('\0')) {
    throw new Error('Null bytes not allowed in entry names');
  }
  if (path.isAbsolute(name)) {
    throw new Error('Absolute paths not allowed in archive entries');
  }
  return true;
}

function extractArchive(archiveData, destDir, opts) {
  opts = opts || {};
  const overwrite = opts.overwrite !== false;

  if (!Array.isArray(archiveData)) {
    throw new TypeError('archiveData must be an array of entries');
  }

  fs.mkdirSync(destDir, { recursive: true });
  const dirCache = new DirectoryCache();
  dirCache.add(destDir);

  const extracted = [];

  for (const entry of archiveData) {
    validateEntryName(entry.name);
    const targetPath = path.join(destDir, entry.name);

    switch (entry.type) {
      case 'directory': {
        if (!fs.existsSync(targetPath)) {
          fs.mkdirSync(targetPath, { recursive: true });
        }
        dirCache.add(targetPath);
        extracted.push({ name: entry.name, type: 'directory' });
        break;
      }

      case 'symlink': {
        if (!entry.target || typeof entry.target !== 'string') {
          throw new Error('Symlink entry must have a target');
        }
        const parentDir = path.dirname(targetPath);
        // Only create symlink if parent directory is known (in cache)
        if (dirCache.has(parentDir) || dirCache.has(targetPath)) {
          try { fs.rmSync(targetPath, { recursive: true, force: true }); } catch (e) {}
          fs.symlinkSync(entry.target, targetPath);
          extracted.push({ name: entry.name, type: 'symlink', target: entry.target });
        }
        break;
      }

      case 'file':
      default: {
        const parentDir = path.dirname(targetPath);
        if (!dirCache.has(parentDir)) {
          fs.mkdirSync(parentDir, { recursive: true });
          dirCache.add(parentDir);
        }

        if (!overwrite && fs.existsSync(targetPath)) {
          continue;
        }

        fs.writeFileSync(targetPath, entry.content || '');
        extracted.push({ name: entry.name, type: 'file' });
        break;
      }
    }
  }

  return { extracted: extracted.length, entries: extracted };
}

function createArchive(sourceDir, opts) {
  opts = opts || {};
  const entries = [];

  function walk(dir, prefix) {
    const items = fs.readdirSync(dir).sort();
    for (const item of items) {
      const fullPath = path.join(dir, item);
      const entryName = prefix ? prefix + '/' + item : item;
      const stat = fs.lstatSync(fullPath);

      if (opts.exclude && opts.exclude.test(entryName)) {
        continue;
      }

      if (stat.isDirectory()) {
        entries.push({ name: entryName, type: 'directory' });
        walk(fullPath, entryName);
      } else if (stat.isSymbolicLink()) {
        entries.push({
          name: entryName,
          type: 'symlink',
          target: fs.readlinkSync(fullPath),
        });
      } else if (stat.isFile()) {
        entries.push({
          name: entryName,
          type: 'file',
          content: fs.readFileSync(fullPath, 'utf8'),
        });
      }
    }
  }

  walk(sourceDir, '');
  return entries;
}

function compressData(data) {
  return zlib.gzipSync(Buffer.from(JSON.stringify(data)));
}

function decompressData(buffer) {
  return JSON.parse(zlib.gunzipSync(buffer).toString());
}

module.exports = { extractArchive, createArchive, compressData, decompressData };
