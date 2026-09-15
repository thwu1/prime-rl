import { SimNode, RandomSource, Force } from '../types';

export function forceCenter(x: number = 0, y: number = 0): Force {
  let nodes: SimNode[];
  const strength = 1;

  const force: Force = function() {
    const n = nodes.length;
    let sx = 0, sy = 0;

    for (let i = 0; i < n; i++) {
      sx += nodes[i].x;
      sy += nodes[i].y;
    }

    sx = (sx / n - x) * strength;
    sy = (sy / n - y) * strength;

    for (let i = 0; i < n; i++) {
      nodes[i].x -= sx;
      nodes[i].y -= sy;
    }
  };

  force.initialize = function(_nodes: SimNode[]) {
    nodes = _nodes;
  };

  return force;
}
