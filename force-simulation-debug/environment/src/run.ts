import { createSimulation } from './simulation';
import { forceCenter } from './forces/center';
import { forceX } from './forces/x';
import { forceManyBody } from './forces/manyBody';
import { forceLink } from './forces/link';
import { forceCollide } from './forces/collide';
import { SimNode } from './types';

function nodeToJSON(n: SimNode) {
  return { index: n.index, x: n.x, y: n.y, vx: n.vx, vy: n.vy };
}

function makeNodes(count: number): any[] {
  return Array.from({ length: count }, () => ({}));
}

const scenarios: Record<string, () => any> = {
  init() {
    const sim = createSimulation(makeNodes(5));
    return sim.nodes().map(nodeToJSON);
  },

  noforce() {
    const sim = createSimulation(makeNodes(3));
    sim.tick(10);
    return sim.nodes().map(nodeToJSON);
  },

  center() {
    const sim = createSimulation(makeNodes(3));
    sim.force('center', forceCenter());
    sim.tick(10);
    return sim.nodes().map(nodeToJSON);
  },

  xforce() {
    const sim = createSimulation(makeNodes(3));
    sim.force('x', forceX());
    sim.tick(10);
    return sim.nodes().map(nodeToJSON);
  },

  link() {
    const sim = createSimulation(makeNodes(2));
    sim.force('link', forceLink([{ source: 0, target: 1 }]));
    sim.tick(10);
    return sim.nodes().map(nodeToJSON);
  },

  manybody() {
    const sim = createSimulation(makeNodes(3));
    sim.force('charge', forceManyBody());
    sim.tick(10);
    return sim.nodes().map(nodeToJSON);
  },

  collide() {
    const nodes = Array.from({ length: 10 }, () => ({ x: 0, y: 0 }));
    const sim = createSimulation(nodes);
    sim.force('collide', forceCollide(5));
    sim.tick(50);
    return sim.nodes().map(nodeToJSON);
  },

  combined() {
    const sim = createSimulation(makeNodes(5));
    sim.force('center', forceCenter());
    sim.force('charge', forceManyBody());
    sim.force('link', forceLink([
      { source: 0, target: 1 },
      { source: 1, target: 2 },
      { source: 2, target: 3 },
      { source: 3, target: 4 },
    ]));
    sim.tick(20);
    return sim.nodes().map(nodeToJSON);
  },

  fixed() {
    const nodes: any[] = [{ fx: 5, fy: 5 }, {}, {}];
    const sim = createSimulation(nodes);
    sim.force('charge', forceManyBody());
    sim.tick(10);
    return sim.nodes().map(nodeToJSON);
  },
};

const arg = process.argv[2];
if (arg === 'all') {
  const results: Record<string, any> = {};
  for (const [name, fn] of Object.entries(scenarios)) {
    results[name] = fn();
  }
  console.log(JSON.stringify(results));
} else if (arg && scenarios[arg]) {
  console.log(JSON.stringify(scenarios[arg]()));
} else {
  console.error('Usage: ts-node run.ts <scenario|all>');
  console.error('Scenarios:', Object.keys(scenarios).join(', '));
  process.exit(1);
}
