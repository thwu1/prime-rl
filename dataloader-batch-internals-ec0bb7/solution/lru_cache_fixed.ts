
interface LRUNode<K, V> {
  key: K;
  value: V;
  prev: LRUNode<K, V> | null;
  next: LRUNode<K, V> | null;
}

export class LRUCacheMap<K, V> {
  private _map: Map<K, LRUNode<K, V>>;
  private _head: LRUNode<K, V> | null;
  private _tail: LRUNode<K, V> | null;
  private _maxSize: number;

  constructor(maxSize: number = 100) {
    this._map = new Map();
    this._head = null;
    this._tail = null;
    this._maxSize = maxSize;
  }

  get(key: K): V | void {
    const node = this._map.get(key);
    if (!node) return undefined;
    // FIX: Move accessed node to tail (MRU position)
    this._moveToTail(node);
    return node.value;
  }

  set(key: K, value: V): void {
    const existingNode = this._map.get(key);
    if (existingNode) {
      existingNode.value = value;
      this._moveToTail(existingNode);
      return;
    }

    while (this._map.size >= this._maxSize && this._head) {
      const evictKey = this._head.key;
      this._removeNode(this._head);
      this._map.delete(evictKey);
    }

    const newNode: LRUNode<K, V> = {
      key,
      value,
      prev: null,
      next: null,
    };

    this._addToTail(newNode);
    this._map.set(key, newNode);
  }

  delete(key: K): void {
    const node = this._map.get(key);
    if (!node) return;
    this._removeNode(node);
    this._map.delete(key);
  }

  clear(): void {
    this._map.clear();
    this._head = null;
    this._tail = null;
  }

  private _moveToTail(node: LRUNode<K, V>): void {
    if (node === this._tail) return;
    this._removeNode(node);
    this._addToTail(node);
  }

  private _removeNode(node: LRUNode<K, V>): void {
    if (node.prev) {
      node.prev.next = node.next;
    } else {
      this._head = node.next;
    }

    if (node.next) {
      node.next.prev = node.prev;
    } else {
      this._tail = node.prev;
    }

    node.prev = null;
    node.next = null;
  }

  private _addToTail(node: LRUNode<K, V>): void {
    if (this._tail) {
      this._tail.next = node;
      node.prev = this._tail;
    } else {
      this._head = node;
    }
    this._tail = node;
  }
}
