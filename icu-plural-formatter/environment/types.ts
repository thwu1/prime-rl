
export enum TYPE {
  literal = 0,
  argument = 1,
  number = 2,
  date = 3,
  time = 4,
  select = 5,
  plural = 6,
  pound = 7,
}

export interface LiteralElement {
  type: TYPE.literal;
  value: string;
}

export interface ArgumentElement {
  type: TYPE.argument;
  value: string;
}

export interface NumberElement {
  type: TYPE.number;
  value: string;
  style: string | null;
}

export interface DateElement {
  type: TYPE.date;
  value: string;
  style: string | null;
}

export interface TimeElement {
  type: TYPE.time;
  value: string;
  style: string | null;
}

export interface PluralOrSelectOption {
  value: MessageFormatElement[];
}

export interface SelectElement {
  type: TYPE.select;
  value: string;
  options: Record<string, PluralOrSelectOption>;
}

export interface PluralElement {
  type: TYPE.plural;
  value: string;
  options: Record<string, PluralOrSelectOption>;
  offset: number;
  pluralType: 'cardinal' | 'ordinal';
}

export interface PoundElement {
  type: TYPE.pound;
}

export type MessageFormatElement =
  | LiteralElement
  | ArgumentElement
  | NumberElement
  | DateElement
  | TimeElement
  | SelectElement
  | PluralElement
  | PoundElement;
