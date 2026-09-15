'use strict';

class DataStore {
  constructor() {
    this._data = new Map();
  }

  set(key, value) {
    this._data.set(key, { value, created: Date.now() });
  }

  get(key) {
    const entry = this._data.get(key);
    return entry ? entry.value : undefined;
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
}

module.exports = DataStore;
