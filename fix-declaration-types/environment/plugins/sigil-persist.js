// sigil-persist.js - Persistence plugin for sigil

(function(root, factory) {
  if (typeof module === 'object' && module.exports) {
    factory(require('../lib/sigil'));
  } else if (typeof define === 'function' && define.amd) {
    define(['sigil'], factory);
  } else {
    factory(root.sigil);
  }
}(typeof self !== 'undefined' ? self : this, function(sigil) {
  'use strict';

  var SignalProto = Object.getPrototypeOf(sigil('__probe__'));

  SignalProto.persist = function(storageKey, serializer) {
    this._storageKey = storageKey;
    this._serializer = serializer || {
      serialize: JSON.stringify,
      deserialize: JSON.parse
    };
    var self = this;
    this.subscribe(function(v) {
      try {
        var data = self._serializer.serialize(v);
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem(storageKey, data);
        }
      } catch(e) { /* storage unavailable */ }
    });
    return this;
  };

  SignalProto.restore = function(fallback) {
    if (typeof localStorage !== 'undefined' && this._storageKey) {
      try {
        var raw = localStorage.getItem(this._storageKey);
        if (raw !== null) {
          this.set(this._serializer.deserialize(raw));
          return this;
        }
      } catch(e) { /* storage unavailable */ }
    }
    if (this._value === undefined && fallback !== undefined) {
      this.set(fallback);
    }
    return this;
  };

  SignalProto.snapshot = function() {
    return {
      key: this._storageKey || this._name,
      value: this._value,
      timestamp: Date.now(),
      dirty: this._index > 0
    };
  };

  SignalProto.derived = function(transform) {
    var self = this;
    var d = sigil(this._name + '.derived');
    this.subscribe(function(v) {
      d.set(transform(v, self.snapshot()));
    });
    return d;
  };
}));
