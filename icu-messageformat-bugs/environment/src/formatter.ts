
import { TYPE, type MessageFormatElement } from './types.js';
import { resolvePluralCategory } from './plural-rules.js';

export function format(
  elements: MessageFormatElement[],
  locale: string,
  values: Record<string, any>,
  currentPluralValue?: number
): string {
  let result = '';

  for (const el of elements) {
    switch (el.type) {
      case TYPE.literal:
        result += el.value;
        break;

      case TYPE.argument: {
        if (!(el.value in values)) {
          throw new Error(`Missing value for '${el.value}'`);
        }
        const val = values[el.value];
        result += val == null ? '' : String(val);
        break;
      }

      case TYPE.number: {
        if (!(el.value in values)) {
          throw new Error(`Missing value for '${el.value}'`);
        }
        const num = Number(values[el.value]);
        let opts: Intl.NumberFormatOptions = {};
        if (el.style === 'integer') {
          opts = { maximumFractionDigits: 0 };
        } else if (el.style === 'currency') {
          opts = { style: 'currency', currency: 'USD' };
        } else if (el.style === 'percent') {
          opts = { style: 'percent' };
        }
        result += new Intl.NumberFormat(locale, opts).format(num);
        break;
      }

      case TYPE.pound: {
        if (typeof currentPluralValue === 'number') {
          result += String(currentPluralValue);
        }
        break;
      }

      case TYPE.select: {
        if (!(el.value in values)) {
          throw new Error(`Missing value for '${el.value}'`);
        }
        const key = String(values[el.value]);
        const opt = el.options[key] || el.options['other'];
        if (!opt) {
          throw new Error(
            `No matching option for '${key}' in select argument '${el.value}'`
          );
        }
        result += format(opt.value, locale, values);
        break;
      }

      case TYPE.plural: {
        if (!(el.value in values)) {
          throw new Error(`Missing value for '${el.value}'`);
        }
        const num = Number(values[el.value]);

        // Try exact match first (=N syntax)
        const exactKey = `=${num}`;
        let opt = el.options[exactKey];

        if (!opt) {
          // Use CLDR plural rules to determine the category
          const category = resolvePluralCategory(locale, num, el.pluralType);
          opt = el.options[category] || el.options['other'];
        }

        if (!opt) {
          throw new Error(
            `No matching plural option for value ${num} in argument '${el.value}'`
          );
        }

        result += format(opt.value, locale, values, num - el.offset);
        break;
      }
    }
  }

  return result;
}
