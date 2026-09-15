import { SimNode, RandomSource, Force } from '../types';
import { Quadtree, createQuadtree, isLeaf, isInternal, QuadNode, QuadLeaf } from '../quadtree';
import { jiggle } from '../jiggle';

export function forceManyBody(): Force {
  let nodes: SimNode[];
  let random: RandomSource;
  let strengths: number[];
  const strengthValue = -30;
  const theta2 = 0.81; // theta = 0.9
  const distanceMin2 = 1;
  const distanceMax2 = Infinity;

  function accumulate(quad: QuadNode<SimNode>): void {
    let strength = 0, weight = 0, x = 0, y = 0;

    if (isInternal(quad)) {
      // Internal node: aggregate from children
      for (let i = 0; i < 4; i++) {
        const q = quad.children[i];
        if (q && Math.abs(q.value) > 0) {
          const c = Math.abs(q.value);
          strength += q.value;
          weight += c;
          x += c * q.x;
          y += c * q.y;
        }
      }
      if (weight > 0) {
        quad.x = x / weight;
        quad.y = y / weight;
      }
    } else {
      // Leaf node: use node position and accumulate strength
      const leaf = quad as QuadLeaf<SimNode>;
      leaf.x = leaf.data.x;
      leaf.y = leaf.data.y;
      let q: QuadLeaf<SimNode> | null = leaf;
      while (q) {
        strength += strengths[q.data.index];
        q = q.next;
      }
    }

    quad.value = strength;
  }

  const force: Force = function(alpha: number) {
    const tree = createQuadtree(
      nodes,
      (d: SimNode) => d.x,
      (d: SimNode) => d.y
    );
    tree.visitAfter(accumulate);

    for (let i = 0; i < nodes.length; i++) {
      const currentNode = nodes[i];

      tree.visit((quad: QuadNode<SimNode>, x1: number, _: number, x2: number) => {
        if (!quad.value) return true;

        let x = quad.x - currentNode.x;
        let y = quad.y - currentNode.y;
        let w = x2 - x1;
        let l = x * x + y * y;

        // Apply Barnes-Hut approximation if possible
        if (w * w / theta2 < l) {
          if (l < distanceMax2) {
            if (x === 0) { x = jiggle(random); l += x * x; }
            if (y === 0) { y = jiggle(random); l += y * y; }
            if (l < distanceMin2) l = Math.sqrt(distanceMin2 * l);
            currentNode.vx += x * quad.value * alpha / l;
            currentNode.vy += y * quad.value * alpha / l;
          }
          return true;
        }

        // Otherwise, process points directly
        if (isInternal(quad) || l >= distanceMax2) return;

        // Leaf node within range
        const leaf = quad as QuadLeaf<SimNode>;
        if (leaf.data !== currentNode || leaf.next) {
          if (x === 0) { x = jiggle(random); l += x * x; }
          if (y === 0) { y = jiggle(random); l += y * y; }
          if (l < distanceMin2) l = Math.sqrt(distanceMin2 * l);
        }

        let q: QuadLeaf<SimNode> | null = leaf;
        while (q) {
          if (q.data !== currentNode) {
            w = strengths[q.data.index] * alpha / l;
            currentNode.vx += x * w;
            currentNode.vy += y * w;
          }
          q = q.next;
        }
      });
    }
  };

  force.initialize = function(_nodes: SimNode[], _random: RandomSource) {
    nodes = _nodes;
    random = _random;
    strengths = new Array(nodes.length);
    for (let i = 0; i < nodes.length; i++) {
      strengths[nodes[i].index] = strengthValue;
    }
  };

  return force;
}
