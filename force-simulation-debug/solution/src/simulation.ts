import { SimNode, RandomSource, Force } from './types';
import { lcg } from './lcg';

const initialRadius = 10;
const initialAngle = Math.PI * (3 - Math.sqrt(5));

export class Simulation {
  private _nodes: SimNode[];
  private _alpha: number = 1;
  private _alphaMin: number = 0.001;
  private _alphaDecay: number;
  private _alphaTarget: number = 0;
  private _velocityDecay: number = 0.4;
  private _forces: Map<string, Force> = new Map();
  private _random: RandomSource;

  constructor(nodes: any[]) {
    this._alphaDecay = 1 - Math.pow(this._alphaMin, 1 / 300);
    this._random = lcg();
    this._nodes = nodes;
    this._initializeNodes();
  }

  private _initializeNodes(): void {
    for (let i = 0; i < this._nodes.length; i++) {
      const node = this._nodes[i];
      node.index = i;
      if (node.fx != null) node.x = node.fx;
      if (node.fy != null) node.y = node.fy;
      if (isNaN(node.x) || isNaN(node.y)) {
        const radius = initialRadius * Math.sqrt(0.5 + i);
        const angle = i * initialAngle;
        node.x = radius * Math.cos(angle);
        node.y = radius * Math.sin(angle);
      }
      if (isNaN(node.vx) || isNaN(node.vy)) {
        node.vx = node.vy = 0;
      }
    }
  }

  private _initializeForce(force: Force): Force {
    if (force.initialize) {
      force.initialize(this._nodes, this._random);
    }
    return force;
  }

  tick(iterations: number = 1): this {
    for (let k = 0; k < iterations; k++) {
      this._alpha += (this._alphaTarget - this._alpha) * this._alphaDecay;

      this._forces.forEach((force) => {
        force(this._alpha);
      });

      for (let i = 0; i < this._nodes.length; i++) {
        const node = this._nodes[i];
        if (node.fx == null) {
          node.vx *= this._velocityDecay;
          node.x += node.vx;
        } else {
          node.x = node.fx;
          node.vx = 0;
        }
        if (node.fy == null) {
          node.vy *= this._velocityDecay;
          node.y += node.vy;
        } else {
          node.y = node.fy;
          node.vy = 0;
        }
      }
    }
    return this;
  }

  force(name: string, force?: Force | null): any {
    if (force === undefined) {
      return this._forces.get(name);
    }
    if (force === null) {
      this._forces.delete(name);
    } else {
      this._forces.set(name, this._initializeForce(force));
    }
    return this;
  }

  nodes(nodes?: any[]): any {
    if (nodes === undefined) return this._nodes;
    this._nodes = nodes;
    this._initializeNodes();
    this._forces.forEach((f) => this._initializeForce(f));
    return this;
  }

  alpha(value?: number): any {
    if (value === undefined) return this._alpha;
    this._alpha = +value;
    return this;
  }

  alphaMin(value?: number): any {
    if (value === undefined) return this._alphaMin;
    this._alphaMin = +value;
    return this;
  }

  alphaDecay(value?: number): any {
    if (value === undefined) return +this._alphaDecay;
    this._alphaDecay = +value;
    return this;
  }

  alphaTarget(value?: number): any {
    if (value === undefined) return this._alphaTarget;
    this._alphaTarget = +value;
    return this;
  }

  velocityDecay(value?: number): any {
    if (value === undefined) return 1 - this._velocityDecay;
    this._velocityDecay = 1 - value;
    return this;
  }
}

export function createSimulation(nodes: any[]): Simulation {
  return new Simulation(nodes);
}
