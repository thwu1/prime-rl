'use strict';

const SEPARATOR = '.';
const MAX_DEPTH = 20;

/**
 * Configuration flattener - converts nested objects to dot-notation
 * and back. Used for environment variable mapping, config file merging,
 * and hierarchical setting overrides.
 */

function isPlainObject(obj) {
  if (Object.prototype.toString.call(obj) !== '[object Object]') return false;
  const proto = Object.getPrototypeOf(obj);
  return proto === null || proto === Object.prototype;
}

function flatten(obj, opts) {
  opts = opts || {};
  const sep = opts.separator || SEPARATOR;
  const maxDepth = opts.maxDepth || MAX_DEPTH;
  const result = {};

  function recurse(current, prefix, depth) {
    if (depth > maxDepth) {
      result[prefix] = current;
      return;
    }
    if (isPlainObject(current)) {
      const keys = Object.keys(current);
      if (keys.length === 0 && prefix) {
        result[prefix] = {};
      }
      for (const key of keys) {
        const newKey = prefix ? prefix + sep + key : key;
        recurse(current[key], newKey, depth + 1);
      }
    } else if (Array.isArray(current)) {
      if (opts.flattenArrays !== false) {
        for (let i = 0; i < current.length; i++) {
          const newKey = prefix ? prefix + sep + i : '' + i;
          recurse(current[i], newKey, depth + 1);
        }
      } else {
        result[prefix] = current;
      }
    } else {
      result[prefix] = current;
    }
  }

  recurse(obj, '', 0);
  return result;
}

function unflatten(data, opts) {
  opts = opts || {};
  const sep = opts.separator || SEPARATOR;
  const result = {};

  for (const flatKey in data) {
    if (!data.hasOwnProperty(flatKey)) continue;

    const keys = flatKey.split(sep);
    let current = result;

    for (let i = 0; i < keys.length - 1; i++) {
      const key = keys[i];
      const nextKey = keys[i + 1];

      if (!(key in current)) {
        // Determine if next level should be array or object
        current[key] = /^\d+$/.test(nextKey) ? [] : {};
      }
      current = current[key];
    }

    const lastKey = keys[keys.length - 1];
    current[lastKey] = data[flatKey];
  }

  return result;
}

function merge(target, source) {
  const flatTarget = flatten(target);
  const flatSource = flatten(source);
  return unflatten(Object.assign({}, flatTarget, flatSource));
}

function diff(a, b) {
  const flatA = flatten(a);
  const flatB = flatten(b);
  const changes = {};
  const allKeys = new Set([...Object.keys(flatA), ...Object.keys(flatB)]);
  for (const key of allKeys) {
    if (flatA[key] !== flatB[key]) {
      changes[key] = { from: flatA[key], to: flatB[key] };
    }
  }
  return changes;
}

module.exports = { flatten, unflatten, merge, diff, isPlainObject };
