import { SimNode } from './types';

// Quadtree node types
export interface QuadLeaf<T> {
  data: T;
  next: QuadLeaf<T> | null;
  x: number;
  y: number;
  value: number;
  r: number;
}

export interface QuadInternal<T> {
  children: (QuadNode<T> | null)[];
  x: number;
  y: number;
  value: number;
  r: number;
}

export type QuadNode<T> = QuadLeaf<T> | QuadInternal<T>;

export function isLeaf<T>(node: QuadNode<T>): node is QuadLeaf<T> {
  return 'data' in node;
}

export function isInternal<T>(node: QuadNode<T>): node is QuadInternal<T> {
  return 'children' in node;
}

function makeLeaf<T>(data: T): QuadLeaf<T> {
  return { data, next: null, x: 0, y: 0, value: 0, r: 0 };
}

function makeInternal<T>(): QuadInternal<T> {
  return { children: [null, null, null, null], x: 0, y: 0, value: 0, r: 0 };
}

interface QueueEntry<T> {
  node: QuadNode<T>;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export class Quadtree<T> {
  _x: (d: T) => number;
  _y: (d: T) => number;
  _x0: number = NaN;
  _y0: number = NaN;
  _x1: number = NaN;
  _y1: number = NaN;
  _root: QuadNode<T> | null = null;

  constructor(x: (d: T) => number, y: (d: T) => number) {
    this._x = x;
    this._y = y;
  }

  cover(x: number, y: number): this {
    if (isNaN(x) || isNaN(y)) return this;

    let x0 = this._x0, y0 = this._y0, x1 = this._x1, y1 = this._y1;

    if (isNaN(x0)) {
      x1 = (x0 = Math.floor(x)) + 1;
      y1 = (y0 = Math.floor(y)) + 1;
    } else {
      let z = x1 - x0 || 1;
      let node: QuadNode<T> | null = this._root;

      while (x0 > x || x >= x1 || y0 > y || y >= y1) {
        const i = ((y < y0 ? 1 : 0) << 1) | (x < x0 ? 1 : 0);
        const parent = makeInternal<T>();
        parent.children[i] = node;
        node = parent;
        z *= 2;
        switch (i) {
          case 0: x1 = x0 + z; y1 = y0 + z; break;
          case 1: x0 = x1 - z; y1 = y0 + z; break;
          case 2: x1 = x0 + z; y0 = y1 - z; break;
          case 3: x0 = x1 - z; y0 = y1 - z; break;
        }
      }

      if (this._root && isInternal(this._root)) {
        this._root = node;
      }
    }

    this._x0 = x0;
    this._y0 = y0;
    this._x1 = x1;
    this._y1 = y1;
    return this;
  }

  add(d: T): this {
    const x = +this._x(d);
    const y = +this._y(d);
    this.cover(x, y);
    return this._addPoint(x, y, d);
  }

  private _addPoint(x: number, y: number, d: T): this {
    if (isNaN(x) || isNaN(y)) return this;

    const leaf = makeLeaf(d);

    if (this._root === null) {
      this._root = leaf;
      return this;
    }

    let node: QuadNode<T> = this._root;
    let x0 = this._x0, y0 = this._y0, x1 = this._x1, y1 = this._y1;
    let parent: QuadInternal<T> | null = null;
    let i = 0;

    // Traverse to find insertion point
    while (isInternal(node)) {
      const xm = (x0 + x1) / 2;
      const ym = (y0 + y1) / 2;
      const right = x >= xm ? 1 : 0;
      const bottom = y >= ym ? 1 : 0;
      if (right) x0 = xm; else x1 = xm;
      if (bottom) y0 = ym; else y1 = ym;
      i = (bottom << 1) | right;
      parent = node;
      const child = node.children[i];
      if (child === null) {
        node.children[i] = leaf;
        return this;
      }
      node = child;
    }

    // node is a leaf - check for coincident point
    const xp = +this._x((node as QuadLeaf<T>).data);
    const yp = +this._y((node as QuadLeaf<T>).data);

    if (x === xp && y === yp) {
      leaf.next = node as QuadLeaf<T>;
      if (parent) parent.children[i] = leaf;
      else this._root = leaf;
      return this;
    }

    // Split until old and new points are separated
    while (true) {
      const newInternal = makeInternal<T>();
      if (parent) {
        parent.children[i] = newInternal;
      } else {
        this._root = newInternal;
      }
      parent = newInternal;

      const xm = (x0 + x1) / 2;
      const ym = (y0 + y1) / 2;
      const right = x >= xm ? 1 : 0;
      const bottom = y >= ym ? 1 : 0;
      if (right) x0 = xm; else x1 = xm;
      if (bottom) y0 = ym; else y1 = ym;
      i = (bottom << 1) | right;
      const j = ((yp >= ym ? 1 : 0) << 1) | (xp >= xm ? 1 : 0);

      if (i !== j) {
        parent.children[j] = node;
        parent.children[i] = leaf;
        break;
      }
    }

    return this;
  }

  addAll(data: T[]): this {
    const n = data.length;
    const xz = new Float64Array(n);
    const yz = new Float64Array(n);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;

    for (let idx = 0; idx < n; idx++) {
      const d = data[idx];
      const x = +this._x(d);
      const y = +this._y(d);
      if (isNaN(x) || isNaN(y)) continue;
      xz[idx] = x;
      yz[idx] = y;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }

    if (x0 > x1 || y0 > y1) return this;

    this.cover(x0, y0);
    this.cover(x1, y1);

    for (let idx = 0; idx < n; idx++) {
      this._addPoint(xz[idx], yz[idx], data[idx]);
    }

    return this;
  }

  visit(callback: (node: QuadNode<T>, x0: number, y0: number, x1: number, y1: number) => boolean | void): this {
    if (!this._root) return this;

    const quads: QueueEntry<T>[] = [
      { node: this._root, x0: this._x0, y0: this._y0, x1: this._x1, y1: this._y1 }
    ];

    while (quads.length) {
      const q = quads.pop()!;
      const { node, x0, y0, x1, y1 } = q;
      if (!callback(node, x0, y0, x1, y1) && isInternal(node)) {
        const xm = (x0 + x1) / 2, ym = (y0 + y1) / 2;
        if (node.children[3]) quads.push({ node: node.children[3], x0: xm, y0: ym, x1, y1 });
        if (node.children[2]) quads.push({ node: node.children[2], x0, y0: ym, x1: xm, y1 });
        if (node.children[1]) quads.push({ node: node.children[1], x0: xm, y0, x1, y1: ym });
        if (node.children[0]) quads.push({ node: node.children[0], x0, y0, x1: xm, y1: ym });
      }
    }

    return this;
  }

  visitAfter(callback: (node: QuadNode<T>, x0: number, y0: number, x1: number, y1: number) => void): this {
    if (!this._root) return this;

    const quads: QueueEntry<T>[] = [
      { node: this._root, x0: this._x0, y0: this._y0, x1: this._x1, y1: this._y1 }
    ];

    while (quads.length) {
      const q = quads.pop()!;
      const { node, x0, y0, x1, y1 } = q;
      callback(node, x0, y0, x1, y1);
      if (isInternal(node)) {
        const xm = (x0 + x1) / 2, ym = (y0 + y1) / 2;
        if (node.children[0]) quads.push({ node: node.children[0], x0, y0, x1: xm, y1: ym });
        if (node.children[1]) quads.push({ node: node.children[1], x0: xm, y0, x1, y1: ym });
        if (node.children[2]) quads.push({ node: node.children[2], x0, y0: ym, x1: xm, y1 });
        if (node.children[3]) quads.push({ node: node.children[3], x0: xm, y0: ym, x1, y1 });
      }
    }

    return this;
  }

  size(): number {
    let s = 0;
    this.visit((node) => {
      if (isLeaf(node)) {
        let n: QuadLeaf<T> | null = node;
        while (n) { s++; n = n.next; }
      }
    });
    return s;
  }

  root(): QuadNode<T> | null {
    return this._root;
  }

  extent(): [[number, number], [number, number]] | undefined {
    return isNaN(this._x0) ? undefined : [[this._x0, this._y0], [this._x1, this._y1]];
  }

  data(): T[] {
    const result: T[] = [];
    this.visit((node) => {
      if (isLeaf(node)) {
        let n: QuadLeaf<T> | null = node;
        while (n) { result.push(n.data); n = n.next; }
      }
    });
    return result;
  }
}

export function createQuadtree<T>(
  data: T[],
  x: (d: T) => number,
  y: (d: T) => number
): Quadtree<T> {
  const tree = new Quadtree(x, y);
  tree.addAll(data);
  return tree;
}
