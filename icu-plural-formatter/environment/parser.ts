
import {
  TYPE,
  MessageFormatElement,
  PluralOrSelectOption,
  LiteralElement,
  PoundElement,
} from './types';

export function parse(message: string): MessageFormatElement[] {
  const p = new Parser(message);
  return p.parseMessage(0, null);
}

class Parser {
  private msg: string;
  private pos: number;

  constructor(msg: string) {
    this.msg = msg;
    this.pos = 0;
  }

  parseMessage(depth: number, parentArgType: string | null): MessageFormatElement[] {
    const els: MessageFormatElement[] = [];
    while (this.pos < this.msg.length) {
      const ch = this.msg[this.pos];
      if (ch === '{') {
        els.push(this.parseArgument(depth));
      } else if (ch === '}' && depth > 0) {
        break;
      } else if (
        ch === '#' &&
        (parentArgType === 'plural' || parentArgType === 'selectordinal')
      ) {
        els.push({ type: TYPE.pound } as PoundElement);
        this.pos++;
      } else {
        const lit = this.parseLiteral(depth, parentArgType);
        if (lit.value) els.push(lit);
      }
    }
    return this.coalesce(els);
  }

  private coalesce(els: MessageFormatElement[]): MessageFormatElement[] {
    const out: MessageFormatElement[] = [];
    for (const el of els) {
      const prev = out.length > 0 ? out[out.length - 1] : null;
      if (
        el.type === TYPE.literal &&
        prev &&
        prev.type === TYPE.literal
      ) {
        (prev as LiteralElement).value += (el as LiteralElement).value;
      } else {
        out.push(el);
      }
    }
    return out;
  }

  private parseLiteral(
    depth: number,
    parentArgType: string | null,
  ): LiteralElement {
    let val = '';
    while (this.pos < this.msg.length) {
      const ch = this.msg[this.pos];
      if (ch === '{' || (ch === '}' && depth > 0)) break;
      if (
        ch === '#' &&
        (parentArgType === 'plural' || parentArgType === 'selectordinal')
      )
        break;

      if (ch === "'") {
        const next =
          this.pos + 1 < this.msg.length ? this.msg[this.pos + 1] : '';

        if (next === "'") {
          // Double apostrophe -> single literal apostrophe
          val += "'";
          this.pos += 2;
          continue;
        }

        // ICU 4.8 rule: apostrophe only starts quoting before syntax chars
        const special =
          next === '{' || next === '}' || next === '<' || next === '>';

        if (special) {
          this.pos++; // skip opening apostrophe
          while (this.pos < this.msg.length) {
            if (this.msg[this.pos] === "'") {
              if (
                this.pos + 1 < this.msg.length &&
                this.msg[this.pos + 1] === "'"
              ) {
                val += "'";
                this.pos += 2;
              } else {
                this.pos++; // skip closing apostrophe
                break;
              }
            } else {
              val += this.msg[this.pos++];
            }
          }
          continue;
        }

        // Plain apostrophe (not before special char) -> literal
        val += "'";
        this.pos++;
        continue;
      }

      val += ch;
      this.pos++;
    }
    return { type: TYPE.literal, value: val };
  }

  private parseArgument(depth: number): MessageFormatElement {
    this.pos++; // skip '{'
    this.ws();
    const name = this.ident();
    this.ws();

    if (this.peek() === '}') {
      this.pos++;
      return { type: TYPE.argument, value: name };
    }

    this.expect(',');
    this.ws();
    const argType = this.ident().toLowerCase();
    this.ws();

    if (argType === 'number' || argType === 'date' || argType === 'time') {
      let style: string | null = null;
      if (this.peek() === ',') {
        this.pos++;
        this.ws();
        style = this.readStyle();
      }
      this.expect('}');
      const typeMap: Record<string, TYPE> = {
        number: TYPE.number,
        date: TYPE.date,
        time: TYPE.time,
      };
      return { type: typeMap[argType], value: name, style } as any;
    }

    if (
      argType === 'plural' ||
      argType === 'selectordinal' ||
      argType === 'select'
    ) {
      this.expect(',');
      this.ws();

      let offset = 0;
      if (
        argType !== 'select' &&
        this.msg.substring(this.pos, this.pos + 7) === 'offset:'
      ) {
        this.pos += 7;
        const neg = this.peek() === '-';
        if (neg) this.pos++;
        const num = this.digits();
        offset = parseInt(num, 10) * (neg ? -1 : 1);
        this.ws();
      }

      const options: Record<string, PluralOrSelectOption> = Object.create(null);
      while (this.pos < this.msg.length && this.peek() !== '}') {
        this.ws();
        if (this.peek() === '}') break;

        let selector: string;
        if (this.peek() === '=') {
          this.pos++;
          const neg = this.peek() === '-';
          if (neg) this.pos++;
          selector = '=' + (neg ? '-' : '') + this.digits();
        } else {
          selector = this.ident();
        }

        this.ws();
        this.expect('{');
        const value = this.parseMessage(depth + 1, argType);
        this.expect('}');
        options[selector] = { value };
        this.ws();
      }
      this.expect('}');

      if (argType === 'select') {
        return { type: TYPE.select, value: name, options };
      }
      return {
        type: TYPE.plural,
        value: name,
        options,
        offset,
        pluralType:
          argType === 'plural'
            ? ('cardinal' as const)
            : ('ordinal' as const),
      };
    }

    throw new Error(`Unknown argument type: ${argType} at position ${this.pos}`);
  }

  private readStyle(): string {
    let s = '';
    let d = 0;
    while (this.pos < this.msg.length) {
      const ch = this.msg[this.pos];
      if (ch === '{') d++;
      else if (ch === '}') {
        if (d === 0) break;
        d--;
      }
      s += ch;
      this.pos++;
    }
    return s.trim();
  }

  private ident(): string {
    let id = '';
    while (this.pos < this.msg.length) {
      const ch = this.msg[this.pos];
      if (/[\s{},#=]/.test(ch)) break;
      id += ch;
      this.pos++;
    }
    return id;
  }

  private digits(): string {
    let n = '';
    while (this.pos < this.msg.length && /[0-9]/.test(this.msg[this.pos])) {
      n += this.msg[this.pos++];
    }
    return n;
  }

  private ws(): void {
    while (this.pos < this.msg.length && /\s/.test(this.msg[this.pos]))
      this.pos++;
  }

  private peek(): string {
    return this.pos < this.msg.length ? this.msg[this.pos] : '';
  }

  private expect(ch: string): void {
    if (this.peek() === ch) this.pos++;
    else
      throw new Error(
        `Expected '${ch}' at position ${this.pos}, got '${this.peek()}'`,
      );
  }
}
