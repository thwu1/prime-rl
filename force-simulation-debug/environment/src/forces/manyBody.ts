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
    // TODO: Implement mass center accumulation for Barnes-Hut approximation
    quad.value = 0;
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
        // TODO: Implement Barnes-Hut force application
        if (!quad.value) return true;
        return true;
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
