import { SimNode, RandomSource, Force } from '../types';
import { Quadtree, createQuadtree, isLeaf, isInternal, QuadNode } from '../quadtree';
import { jiggle } from '../jiggle';

export function forceCollide(radiusValue: number = 1): Force {
  let nodes: SimNode[];
  let random: RandomSource;
  let radii: number[];
  const strength = 1;
  const iterations = 1;

  function prepare(quad: QuadNode<SimNode>): void {
    // TODO: Propagate maximum collision radius through the quadtree
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
          // TODO: Implement collision detection and resolution
          return undefined;
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
