/**
 * A simple linear document model representing text as a string.
 * Positions are zero-based character indices.
 */
export class Doc {
  constructor(readonly content: string) {}

  get size(): number {
    return this.content.length
  }

  textBetween(from: number, to: number): string {
    return this.content.substring(from, to)
  }

  replace(from: number, to: number, text: string): Doc {
    return new Doc(
      this.content.substring(0, from) + text + this.content.substring(to)
    )
  }

  eq(other: Doc): boolean {
    return this.content === other.content
  }

  toString(): string {
    return `Doc(${JSON.stringify(this.content)})`
  }
}
