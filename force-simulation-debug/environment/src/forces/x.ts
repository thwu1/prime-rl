import { SimNode, RandomSource, Force } from '../types';

export function forceX(targetX: number = 0): Force {
  let nodes: SimNode[];
  const strengthValue = 0.1;

  const force: Force = function(alpha: number) {
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      node.vx += (targetX - node.x) * strengthValue * alpha;
    }
  };

  force.initialize = function(_nodes: SimNode[]) {
    nodes = _nodes;
  };

  return force;
}
