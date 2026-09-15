
import {
  MessageFormatElement,
  TYPE,
  LiteralElement,
  ArgumentElement,
  NumberElement,
  SelectElement,
  PluralElement,
} from './types';
import { resolvePlural } from './plural-rules';

const _hasOwn = Object.prototype.hasOwnProperty;

export function format(
  ast: MessageFormatElement[],
  locale: string,
  values: Record<string, any>,
  currentPluralValue?: number,
): string {
  const parts: string[] = [];

  for (const el of ast) {
    switch (el.type) {
      case TYPE.literal: {
        parts.push((el as LiteralElement).value);
        break;
      }

      case TYPE.argument: {
        const val = values[(el as ArgumentElement).value];
        if (val === false || val === null || val === undefined) {
          parts.push('');
        } else {
          parts.push(String(val));
        }
        break;
      }

      case TYPE.number: {
        const numEl = el as NumberElement;
        const val = values[numEl.value];
        parts.push(new Intl.NumberFormat(locale).format(val as number));
        break;
      }

      case TYPE.pound: {
        if (currentPluralValue !== undefined) {
          // Keep grouping locale-sensitive while using Latin decimal digits,
          // which is the wire-format convention expected by this formatter.
          parts.push(new Intl.NumberFormat(`${locale}-u-nu-latn`).format(currentPluralValue));
        } else {
          parts.push('#');
        }
        break;
      }

      case TYPE.select: {
        const selEl = el as SelectElement;
        const val = String(values[selEl.value]);
        let option;
        if (_hasOwn.call(selEl.options, val)) {
          option = selEl.options[val];
        } else if (_hasOwn.call(selEl.options, 'other')) {
          option = selEl.options['other'];
        }
        if (option) {
          parts.push(format(option.value, locale, values, currentPluralValue));
        }
        break;
      }

      case TYPE.plural: {
        const plEl = el as PluralElement;
        const rawVal = Number(values[plEl.value]);
        const offsetVal = rawVal - (plEl.offset || 0);

        // 1. Check exact match against RAW value
        const exactKey = '=' + String(rawVal);
        let option;
        if (_hasOwn.call(plEl.options, exactKey)) {
          option = plEl.options[exactKey];
        } else {
          // 2. Resolve plural category using OFFSET-ADJUSTED value
          const category = resolvePlural(
            offsetVal,
            locale,
            plEl.pluralType,
          );
          if (_hasOwn.call(plEl.options, category)) {
            option = plEl.options[category];
          } else if (_hasOwn.call(plEl.options, 'other')) {
            option = plEl.options['other'];
          }
        }

        if (option) {
          // 3. Pass OFFSET-ADJUSTED value as currentPluralValue for # replacement
          parts.push(format(option.value, locale, values, offsetVal));
        }
        break;
      }

      default:
        break;
    }
  }

  return parts.join('');
}
