import { SimNode, RandomSource, Force } from '../types';
import { jiggle } from '../jiggle';

interface LinkInput {
  source: number | SimNode;
  target: number | SimNode;
  index?: number;
}

interface ResolvedLink {
  source: SimNode;
  target: SimNode;
  index: number;
}

export function forceLink(links: LinkInput[]): Force {
  let nodes: SimNode[];
  let random: RandomSource;
  let resolvedLinks: ResolvedLink[];
  let biases: number[];
  let strengths: number[];
  let distances: number[];
  let counts: number[];
  const iterations = 1;

  const force: Force = function(alpha: number) {
    for (let k = 0; k < iterations; k++) {
      for (let i = 0; i < resolvedLinks.length; i++) {
        const link = resolvedLinks[i];
        const source = link.source;
        const target = link.target;
        let x = target.x + target.vx - source.x - source.vx || jiggle(random);
        let y = target.y + target.vy - source.y - source.vy || jiggle(random);
        let l = Math.sqrt(x * x + y * y);
        l = (l - distances[i]) / l * alpha * strengths[i];
        x *= l;
        y *= l;
        let b = biases[i];
        target.vx -= x * b;
        target.vy -= y * b;
        source.vx += x * (1 - b);
        source.vy += y * (1 - b);
      }
    }
  };

  force.initialize = function(_nodes: SimNode[], _random: RandomSource) {
    nodes = _nodes;
    random = _random;

    const nodeById = new Map<number, SimNode>();
    for (let i = 0; i < nodes.length; i++) {
      nodeById.set(nodes[i].index, nodes[i]);
    }

    resolvedLinks = [];
    counts = new Array(nodes.length).fill(0);

    for (let i = 0; i < links.length; i++) {
      const link = links[i];
      const source = typeof link.source === 'object' ? link.source : nodeById.get(link.source as number)!;
      const target = typeof link.target === 'object' ? link.target : nodeById.get(link.target as number)!;
      resolvedLinks.push({ source, target, index: i });
      counts[source.index] = (counts[source.index] || 0) + 1;
      counts[target.index] = (counts[target.index] || 0) + 1;
    }

    biases = new Array(resolvedLinks.length);
    for (let i = 0; i < resolvedLinks.length; i++) {
      const link = resolvedLinks[i];
      biases[i] = counts[link.target.index] / (counts[link.source.index] + counts[link.target.index]);
    }

    strengths = new Array(resolvedLinks.length);
    distances = new Array(resolvedLinks.length);
    for (let i = 0; i < resolvedLinks.length; i++) {
      const link = resolvedLinks[i];
      strengths[i] = 1 / Math.min(counts[link.source.index], counts[link.target.index]);
      distances[i] = 30;
    }
  };

  return force;
}
