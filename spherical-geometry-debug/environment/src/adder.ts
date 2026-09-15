/**
 * Compensated summation using Neumaier's improved Kahan algorithm.
 * Provides higher numerical precision for sums of floating-point numbers.
 */
export class Adder {
  private s = 0;
  private c = 0;

  add(value: number): this {
    const t = this.s + value;
    if (Math.abs(this.s) >= Math.abs(value)) {
      this.c += (this.s - t) + value;
    } else {
      this.c += (value - t) + this.s;
    }
    this.s = t;
    return this;
  }

  valueOf(): number {
    return this.s + this.c;
  }
}
