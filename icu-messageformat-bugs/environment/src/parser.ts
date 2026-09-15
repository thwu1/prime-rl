
import {
  TYPE,
  type MessageFormatElement,
  type LiteralElement,
  type PluralOrSelectOption,
} from './types.js';

type ArgType = 'number' | 'select' | 'plural' | 'selectordinal' | '';

export class Parser {
  private message: string;
  private pos: number;

  constructor(message: string) {
    this.message = message;
    this.pos = 0;
  }

  parse(): MessageFormatElement[] {
    return this.parseMessage(0, '');
  }

  private parseMessage(
    nestingLevel: number,
    parentArgType: ArgType
  ): MessageFormatElement[] {
    const elements: MessageFormatElement[] = [];

    while (this.pos < this.message.length) {
      const ch = this.message[this.pos];

      if (ch === '{') {
        elements.push(this.parseArgument(nestingLevel));
      } else if (ch === '}' && nestingLevel > 0) {
        break;
      } else if (
        ch === '#' &&
        (parentArgType === 'plural' || parentArgType === 'selectordinal')
      ) {
        this.pos++;
        elements.push({ type: TYPE.pound });
      } else {
        const literal = this.parseLiteral(nestingLevel, parentArgType);
        if (literal.value.length > 0) {
          elements.push(literal);
        }
      }
    }

    return elements;
  }

  private parseLiteral(
    nestingLevel: number,
    parentArgType: ArgType
  ): LiteralElement {
    let value = '';

    while (this.pos < this.message.length) {
      const ch = this.message[this.pos];

      const quoteResult = this.tryParseQuote(parentArgType);
      if (quoteResult !== null) {
        value += quoteResult;
        continue;
      }

      if (ch === '{') break;
      if (ch === '}' && nestingLevel > 0) break;
      if (
        ch === '#' &&
        (parentArgType === 'plural' || parentArgType === 'selectordinal')
      )
        break;

      value += ch;
      this.pos++;
    }

    return { type: TYPE.literal, value };
  }

  /**
   * ICU 4.8+ quoting: an apostrophe starts quoted text only when immediately
   * before a character that requires quoting ({, }, <, >, or # inside
   * plural/selectordinal). A pair of apostrophes '' always represents one
   * literal apostrophe.
   */
  private tryParseQuote(parentArgType: ArgType): string | null {
    if (this.pos >= this.message.length || this.message[this.pos] !== "'") {
      return null;
    }

    const nextPos = this.pos + 1;
    const nextChar =
      nextPos < this.message.length ? this.message[nextPos] : null;

    // Double apostrophe '' → literal apostrophe
    if (nextChar === "'") {
      this.pos += 2;
      return '';
    }

    // Determine whether the apostrophe starts a quoted region
    const shouldQuote =
      nextChar === '{' ||
      nextChar === '}' ||
      nextChar === '<' ||
      nextChar === '>';

    if (!shouldQuote) {
      return null;
    }

    // Consume the opening apostrophe and read quoted text
    this.pos++;
    let result = '';
    while (this.pos < this.message.length) {
      const ch = this.message[this.pos];
      if (ch === "'") {
        if (
          this.pos + 1 < this.message.length &&
          this.message[this.pos + 1] === "'"
        ) {
          // Double apostrophe inside quoted region → literal apostrophe
          result += "'";
          this.pos += 2;
          continue;
        } else {
          // Closing apostrophe ends the quoted region
          this.pos++;
          break;
        }
      }
      result += ch;
      this.pos++;
    }

    return result;
  }

  private parseArgument(nestingLevel: number): MessageFormatElement {
    this.pos++; // skip '{'
    this.skipWhitespace();

    if (this.pos >= this.message.length) {
      throw new Error('Unclosed argument brace');
    }

    if (this.message[this.pos] === '}') {
      this.pos++;
      throw new Error('Empty argument');
    }

    const name = this.parseIdentifier();
    if (!name) {
      throw new Error('Malformed argument: expected identifier');
    }

    this.skipWhitespace();

    if (this.pos >= this.message.length) {
      throw new Error('Unclosed argument brace');
    }

    // Simple argument: {name}
    if (this.message[this.pos] === '}') {
      this.pos++;
      return { type: TYPE.argument, value: name };
    }

    // Typed argument: {name, type, ...}
    if (this.message[this.pos] !== ',') {
      throw new Error('Malformed argument: expected , or }');
    }
    this.pos++; // skip ','
    this.skipWhitespace();

    const argType = this.parseIdentifier();
    this.skipWhitespace();

    switch (argType) {
      case 'number':
        return this.parseNumberArgument(name);
      case 'plural':
      case 'selectordinal':
      case 'select':
        return this.parsePluralOrSelectArgument(name, argType);
      default:
        throw new Error(`Unsupported argument type: ${argType}`);
    }
  }

  private parseNumberArgument(name: string): MessageFormatElement {
    let style: string | null = null;

    if (this.pos < this.message.length && this.message[this.pos] === ',') {
      this.pos++; // skip ','
      this.skipWhitespace();

      const styleStart = this.pos;
      let braceDepth = 0;
      while (this.pos < this.message.length) {
        const ch = this.message[this.pos];
        if (ch === '{') {
          braceDepth++;
          this.pos++;
        } else if (ch === '}') {
          if (braceDepth > 0) {
            braceDepth--;
            this.pos++;
          } else {
            break;
          }
        } else {
          this.pos++;
        }
      }
      style = this.message.slice(styleStart, this.pos).trim();
      if (style.length === 0) style = null;
    }

    if (this.pos >= this.message.length || this.message[this.pos] !== '}') {
      throw new Error('Unclosed number argument');
    }
    this.pos++;

    return { type: TYPE.number, value: name, style };
  }

  private parsePluralOrSelectArgument(
    name: string,
    argType: string
  ): MessageFormatElement {
    if (this.pos >= this.message.length || this.message[this.pos] !== ',') {
      throw new Error(`Expected ',' after ${argType}`);
    }
    this.pos++; // skip ','
    this.skipWhitespace();

    // Parse optional offset for plural/selectordinal
    let offset = 0;
    if (argType !== 'select') {
      const savedPos = this.pos;
      const possibleOffset = this.parseIdentifier();
      if (possibleOffset === 'offset') {
        if (
          this.pos >= this.message.length ||
          this.message[this.pos] !== ':'
        ) {
          throw new Error('Expected : after offset');
        }
        this.pos++; // skip ':'
        this.skipWhitespace();
        this.parseDecimalInteger();
        this.skipWhitespace();
      } else {
        this.pos = savedPos;
      }
    }

    // Parse selector → body pairs
    const options: Record<string, PluralOrSelectOption> = {};

    while (this.pos < this.message.length && this.message[this.pos] !== '}') {
      this.skipWhitespace();
      if (this.pos >= this.message.length || this.message[this.pos] === '}')
        break;

      // Parse selector keyword (e.g. "one", "other") or exact value (e.g. "=0")
      let selector = '';
      if (argType !== 'select' && this.message[this.pos] === '=') {
        this.pos++; // skip '='
        selector = '=' + this.parseDecimalInteger().toString();
      } else {
        selector = this.parseIdentifier();
      }

      if (!selector) break;

      this.skipWhitespace();

      if (this.pos >= this.message.length || this.message[this.pos] !== '{') {
        throw new Error(`Expected '{' after selector '${selector}'`);
      }
      this.pos++; // skip '{'

      const body = this.parseMessage(1, argType as ArgType);

      if (this.pos >= this.message.length || this.message[this.pos] !== '}') {
        throw new Error('Unclosed selector body');
      }
      this.pos++; // skip '}'

      options[selector] = { value: body };
      this.skipWhitespace();
    }

    if (this.pos >= this.message.length || this.message[this.pos] !== '}') {
      throw new Error('Unclosed plural/select argument');
    }
    this.pos++; // skip '}'

    if (argType === 'select') {
      return {
        type: TYPE.select,
        value: name,
        options,
      };
    } else {
      return {
        type: TYPE.plural,
        value: name,
        options,
        offset,
        pluralType: 'cardinal',
      };
    }
  }

  private parseIdentifier(): string {
    const start = this.pos;
    while (this.pos < this.message.length) {
      const ch = this.message[this.pos];
      if (/[\s{}=,:#]/.test(ch)) break;
      this.pos++;
    }
    return this.message.slice(start, this.pos);
  }

  private parseDecimalInteger(): number {
    let sign = 1;
    if (this.pos < this.message.length && this.message[this.pos] === '+') {
      this.pos++;
    } else if (
      this.pos < this.message.length &&
      this.message[this.pos] === '-'
    ) {
      sign = -1;
      this.pos++;
    }

    const start = this.pos;
    while (
      this.pos < this.message.length &&
      this.message[this.pos] >= '0' &&
      this.message[this.pos] <= '9'
    ) {
      this.pos++;
    }

    if (this.pos === start) {
      throw new Error('Expected decimal integer');
    }

    return sign * parseInt(this.message.slice(start, this.pos), 10);
  }

  private skipWhitespace(): void {
    while (
      this.pos < this.message.length &&
      /\s/.test(this.message[this.pos])
    ) {
      this.pos++;
    }
  }
}
