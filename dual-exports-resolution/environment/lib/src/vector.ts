export class Vector {
  constructor(public readonly components: number[]) {}

  get dimension(): number {
    return this.components.length;
  }

  add(other: Vector): Vector {
    if (this.dimension !== other.dimension) {
      throw new Error("Dimension mismatch");
    }
    return new Vector(this.components.map((v, i) => v + other.components[i]));
  }

  dot(other: Vector): number {
    if (this.dimension !== other.dimension) {
      throw new Error("Dimension mismatch");
    }
    return this.components.reduce((sum, v, i) => sum + v * other.components[i], 0);
  }

  scale(factor: number): Vector {
    return new Vector(this.components.map(v => v * factor));
  }

  normalize(): Vector {
    const mag = Math.sqrt(this.dot(this));
    if (mag === 0) throw new Error("Cannot normalize zero vector");
    return this.scale(1 / mag);
  }

  cross(other: Vector): Vector {
    if (this.dimension !== 3 || other.dimension !== 3) {
      throw new Error("Cross product requires 3D vectors");
    }
    const [a1, a2, a3] = this.components;
    const [b1, b2, b3] = other.components;
    return new Vector([
      a2 * b3 - a3 * b2,
      a3 * b1 - a1 * b3,
      a1 * b2 - a2 * b1,
    ]);
  }
}
