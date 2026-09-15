'use strict';

const FileStore = require('./persistence');

class DataStore {
  constructor(opts) {
    if (!opts) opts = {};
    this._data = new Map();
    this._persist = opts.persist ? new FileStore(opts.persistDir) : null;
  }

  set(key, value) {
    this._data.set(key, { value, created: Date.now() });
    if (this._persist) {
      this._persist.save(key, value);
    }
  }

  get(key) {
    const entry = this._data.get(key);
    if (entry) return entry.value;
    if (this._persist) {
      const val = this._persist.load(key);
      if (val !== null) {
        this._data.set(key, { value: val, created: Date.now() });
        return val;
      }
    }
    return undefined;
  }

  delete(key) {
    return this._data.delete(key);
  }

  has(key) {
    return this._data.has(key);
  }

  keys() {
    return Array.from(this._data.keys());
  }

  clear() {
    this._data.clear();
  }

  size() {
    return this._data.size;
  }
}

module.exports = DataStore;
