import { SimNode, RandomSource, Force } from '../types';
import { Quadtree, createQuadtree, isLeaf, isInternal, QuadNode, QuadLeaf } from '../quadtree';
import { jiggle } from '../jiggle';

export function forceCollide(radiusValue: number = 1): Force {
  let nodes: SimNode[];
  let random: RandomSource;
  let radii: number[];
  const strength = 1;
  const iterations = 1;

  function prepare(quad: QuadNode<SimNode>): void {
    if (isLeaf(quad)) {
      quad.r = radii[quad.data.index];
      return;
    }
    // Internal node: max radius of children
    quad.r = 0;
    for (let i = 0; i < 4; i++) {
      const child = (quad as any).children[i];
      if (child && child.r > quad.r) {
        quad.r = child.r;
      }
    }
  }

  const force: Force = function() {
    for (let k = 0; k < iterations; k++) {
      const tree = createQuadtree(
        nodes,
        (d: SimNode) => d.x + d.vx,
        (d: SimNode) => d.y + d.vy
      );
      tree.visitAfter(prepare);

      for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        const ri = radii[node.index];
        const ri2 = ri * ri;
        const xi = node.x + node.vx;
        const yi = node.y + node.vy;

        tree.visit((quad: QuadNode<SimNode>, x0: number, y0: number, x1: number, y1: number) => {
          if (isLeaf(quad)) {
            const data = quad.data;
            if (data.index > node.index) {
              const rj = quad.r;
              const r = ri + rj;
              let x = xi - data.x - data.vx;
              let y = yi - data.y - data.vy;
              let l = x * x + y * y;
              if (l < r * r) {
                if (x === 0) { x = jiggle(random); l += x * x; }
                if (y === 0) { y = jiggle(random); l += y * y; }
                const lSqrt = Math.sqrt(l);
                const lVal = (r - lSqrt) / lSqrt * strength;
                x *= lVal;
                y *= lVal;
                const rjSq = rj * rj;
                const rRatio = rjSq / (ri2 + rjSq);
                node.vx += x * rRatio;
                node.vy += y * rRatio;
                data.vx -= x * (1 - rRatio);
                data.vy -= y * (1 - rRatio);
              }
            }
            return;  // Don't traverse children of leaf
          }

          // Internal node: check if quadrant could contain overlapping nodes
          const rj = quad.r;
          const r = ri + rj;
          return x0 > xi + r || x1 < xi - r || y0 > yi + r || y1 < yi - r;
        });
      }
    }
  };

  force.initialize = function(_nodes: SimNode[], _random: RandomSource) {
    nodes = _nodes;
    random = _random;
    radii = new Array(nodes.length);
    for (let i = 0; i < nodes.length; i++) {
      radii[nodes[i].index] = radiusValue;
    }
  };

  return force;
}
