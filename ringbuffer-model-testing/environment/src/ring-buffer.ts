
export type OverflowPolicy = 'drop-oldest' | 'drop-newest' | 'reject';

export interface RingBufferConfig {
  capacity: number;
  policy?: OverflowPolicy;
}

export class RingBuffer<T> {
  private buf: (T | undefined)[];
  private readPos: number = 0;
  private writePos: number = 0;
  private _size: number = 0;
  private readonly _capacity: number;
  private _policy: OverflowPolicy;

  constructor(config: RingBufferConfig) {
    if (config.capacity < 1) {
      throw new RangeError('RingBuffer capacity must be at least 1');
    }
    this._capacity = Math.floor(config.capacity);
    this._policy = config.policy ?? 'drop-oldest';
    this.buf = new Array<T | undefined>(this._capacity).fill(undefined);
  }

  /** Current number of items in the buffer. */
  get size(): number {
    return this._size;
  }

  /** Maximum number of items the buffer can hold. */
  get capacity(): number {
    return this._capacity;
  }

  /** Current overflow policy. */
  get policy(): OverflowPolicy {
    return this._policy;
  }

  /** Whether the buffer contains no items. */
  get isEmpty(): boolean {
    return this._size === 0;
  }

  /** Whether the buffer is at full capacity. */
  get isFull(): boolean {
    return this._size === this._capacity;
  }

  /** Change the overflow policy at runtime. */
  setPolicy(policy: OverflowPolicy): void {
    this._policy = policy;
  }

  /**
   * Enqueue an item at the tail of the buffer.
   * Returns true if the item was accepted, false if rejected by the current policy.
   */
  push(item: T): boolean {
    if (this._size === this._capacity) {
      switch (this._policy) {
        case 'reject':
          return false;
        case 'drop-newest':
          return false;
        case 'drop-oldest':
          this.readPos = (this.readPos + 1) % this._capacity;
          this._size--;
          break;
      }
    }
    this.buf[this.writePos] = item;
    this.writePos = (this.writePos + 1) % this._capacity;
    this._size++;
    return true;
  }

  /**
   * Dequeue and return the item at the head of the buffer.
   * Returns undefined if the buffer is empty.
   */
  pop(): T | undefined {
    if (this._size === 0) return undefined;
    const item = this.buf[this.readPos] as T;
    this.buf[this.readPos] = undefined;
    this.readPos = (this.readPos + 1) % this._capacity;
    this._size--;
    return item;
  }

  /**
   * Return the item at position offset from the head without removing it.
   * Offset 0 is the head (oldest item). Returns undefined if out of range.
   */
  peek(offset: number = 0): T | undefined {
    if (offset < 0 || offset >= this._size) return undefined;
    return this.buf[this.readPos + offset] as T | undefined;
  }

  /**
   * Push multiple items sequentially.
   * Returns the number of items that were actually accepted.
   */
  pushMany(items: T[]): number {
    let accepted = 0;
    for (const item of items) {
      this.push(item);
      accepted++;
    }
    return accepted;
  }

  /**
   * Return a snapshot of all items in FIFO order (head to tail).
   * Does not modify the buffer.
   */
  toArray(): T[] {
    if (this._size === 0) return [];
    const result: T[] = [];
    if (this.readPos <= this.writePos) {
      for (let i = this.readPos; i < this.writePos; i++) {
        result.push(this.buf[i] as T);
      }
    } else {
      for (let i = this.readPos; i < this._capacity; i++) {
        result.push(this.buf[i] as T);
      }
      for (let i = 0; i < this.writePos; i++) {
        result.push(this.buf[i] as T);
      }
    }
    return result;
  }

  /** Remove all items and reset the buffer to its initial state. */
  clear(): void {
    this.buf.fill(undefined);
    this.readPos = 0;
    this.writePos = 0;
    this._size = 0;
  }
}
