// sigil.js - Reactive signal library (UMD)

(function(root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.sigil = factory();
  }
}(typeof self !== 'undefined' ? self : this, function() {
  'use strict';

  function sigil(name, options) {
    if (!(this instanceof sigil)) {
      return new sigil(name, options);
    }
    this._name = name;
    this._options = options || {};
    this._value = undefined;
    this._listeners = [];
    this._eventHandlers = {};
    this._index = 0;
  }

  Object.defineProperty(sigil.prototype, 'name', {
    get: function() { return this._name; },
    enumerable: true
  });

  sigil.prototype.get = function() {
    return this._value;
  };

  sigil.prototype.peek = function() {
    return this._value;
  };

  sigil.prototype.set = function(value) {
    var old = this._value;
    this._value = value;
    var self = this;
    this._listeners.forEach(function(fn) {
      fn(value, self._index++);
    });
    if (this._eventHandlers['change']) {
      this._eventHandlers['change'].forEach(function(h) { h(value); });
    }
    return this;
  };

  sigil.prototype.update = function(fn) {
    return this.set(fn(this._value));
  };

  sigil.prototype.subscribe = function(listener) {
    this._listeners.push(listener);
    var listeners = this._listeners;
    return {
      unsubscribe: function() {
        var idx = listeners.indexOf(listener);
        if (idx >= 0) listeners.splice(idx, 1);
      },
      closed: false
    };
  };

  sigil.prototype.on = function(event, handler) {
    if (!this._eventHandlers[event]) {
      this._eventHandlers[event] = [];
    }
    this._eventHandlers[event].push(handler);
    return this;
  };

  sigil.prototype.once = function(event, handler) {
    var self = this;
    var wrapper = function() {
      handler.apply(null, arguments);
      var idx = self._eventHandlers[event].indexOf(wrapper);
      if (idx >= 0) self._eventHandlers[event].splice(idx, 1);
    };
    return this.on(event, wrapper);
  };

  sigil.prototype.pipe = function(op) {
    if (typeof op === 'string') {
      var args = Array.prototype.slice.call(arguments, 1);
      switch (op) {
        case 'map':
          return mapOp(this, args[0]);
        case 'filter':
          return filterOp(this, args[0]);
        case 'debounce':
          return debounceOp(this, args[0]);
        case 'take':
          return takeOp(this, args[0]);
        case 'scan':
          return scanOp(this, args[0], args[1]);
        case 'switchMap':
          return switchMapOp(this, args[0]);
        case 'pairwise':
          return pairwiseOp(this);
        case 'distinctUntilChanged':
          return distinctOp(this);
        default:
          return new sigil(this._name + '.' + op);
      }
    }
    return op(this);
  };

  // ---- Pipe operator implementations ----

  function mapOp(source, fn) {
    var s = new sigil(source._name + '.map');
    source.subscribe(function(v) { s.set(fn(v)); });
    return s;
  }

  function filterOp(source, predicate) {
    var s = new sigil(source._name + '.filter');
    source.subscribe(function(v) { if (predicate(v)) s.set(v); });
    return s;
  }

  function debounceOp(source, ms) {
    var s = new sigil(source._name + '.debounce');
    var timer = null;
    source.subscribe(function(v) {
      clearTimeout(timer);
      timer = setTimeout(function() { s.set(v); }, ms);
    });
    return s;
  }

  function takeOp(source, count) {
    var s = new sigil(source._name + '.take');
    var taken = 0;
    source.subscribe(function(v) {
      if (taken < count) { s.set(v); taken++; }
    });
    return s;
  }

  function scanOp(source, reducer, seed) {
    var s = new sigil(source._name + '.scan');
    var acc = seed;
    source.subscribe(function(v) {
      acc = reducer(acc, v);
      s.set(acc);
    });
    return s;
  }

  function switchMapOp(source, fn) {
    var s = new sigil(source._name + '.switchMap');
    var innerSub = null;
    source.subscribe(function(v) {
      if (innerSub) innerSub.unsubscribe();
      var inner = fn(v);
      innerSub = inner.subscribe(function(iv) { s.set(iv); });
    });
    return s;
  }

  function pairwiseOp(source) {
    var s = new sigil(source._name + '.pairwise');
    var prev = undefined;
    var hasPrev = false;
    source.subscribe(function(v) {
      if (hasPrev) s.set([prev, v]);
      prev = v;
      hasPrev = true;
    });
    return s;
  }

  function distinctOp(source) {
    var s = new sigil(source._name + '.distinct');
    var last = undefined;
    var hasLast = false;
    source.subscribe(function(v) {
      if (!hasLast || v !== last) {
        s.set(v);
        last = v;
        hasLast = true;
      }
    });
    return s;
  }

  // ---- Static factory methods ----

  sigil.of = function(value) {
    var s = new sigil('of');
    s.set(value);
    return s;
  };

  sigil.computed = function(deps, fn) {
    var s = new sigil('computed');
    function recompute() {
      var values = deps.map(function(d) { return d.get(); });
      s.set(fn.apply(null, values));
    }
    deps.forEach(function(d) { d.subscribe(recompute); });
    recompute();
    return s;
  };

  sigil.combine = function() {
    var signals = Array.prototype.slice.call(arguments);
    var combined = new sigil('combined');
    var values = new Array(signals.length);
    signals.forEach(function(sig, i) {
      sig.subscribe(function(v) {
        values[i] = v;
        combined.set(values.slice());
      });
    });
    return combined;
  };

  sigil.merge = function() {
    var signals = Array.prototype.slice.call(arguments);
    var merged = new sigil('merged');
    signals.forEach(function(sig) {
      sig.subscribe(function(v) { merged.set(v); });
    });
    return merged;
  };

  sigil.fromEvent = function(target, eventName) {
    var s = new sigil(eventName);
    if (target.addEventListener) {
      target.addEventListener(eventName, function(e) { s.set(e); });
    }
    return s;
  };

  sigil.fromPromise = function(promise) {
    var s = new sigil('promise');
    promise.then(function(v) { s.set(v); });
    return s;
  };

  sigil.batch = function(fn) {
    fn();
  };

  sigil.EMPTY = new sigil('EMPTY');
  sigil.version = '2.0.0';

  return sigil;
}));
