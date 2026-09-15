
/**
 * Resolve the CLDR plural category for a given number and locale.
 *
 * Supports integer values for cardinal (en, fr, ar, cy, ru, pt, pl, ja)
 * and ordinal (en) plural types.
 */
export function resolvePlural(
  n: number,
  locale: string,
  type: 'cardinal' | 'ordinal',
): string {
  const base = locale.split('-')[0].toLowerCase();
  const absN = Math.abs(n);
  const i = Math.floor(absN);

  if (type === 'ordinal') {
    return resolveOrdinal(i, base);
  }
  return resolveCardinal(absN, i, base);
}

function resolveCardinal(n: number, i: number, locale: string): string {
  switch (locale) {
    case 'en': {
      if (i === 1) return 'one';
      return 'other';
    }

    case 'fr': {
      if (i === 1) return 'one';
      return 'other';
    }

    case 'ar': {
      if (n === 0) return 'zero';
      if (n === 1) return 'one';
      if (n === 2) return 'two';
      const mod100 = i % 100;
      if (mod100 >= 3 && mod100 <= 10) return 'few';
      if (mod100 >= 11 && mod100 <= 98) return 'many';
      return 'other';
    }

    case 'cy': {
      if (n === 0) return 'zero';
      if (n === 1) return 'one';
      if (n === 2) return 'two';
      if (n === 3) return 'few';
      if (n === 6) return 'many';
      return 'other';
    }

    case 'ru': {
      if (i % 10 === 1) return 'one';
      if (i % 10 >= 2 && i % 10 <= 4 && !(i % 100 >= 12 && i % 100 <= 14))
        return 'few';
      if (
        i % 10 === 0 ||
        (i % 10 >= 5 && i % 10 <= 9) ||
        (i % 100 >= 11 && i % 100 <= 14)
      )
        return 'many';
      return 'other';
    }

    case 'pt': {
      if (i === 1) return 'one';
      return 'other';
    }

    case 'pl': {
      if (i === 1) return 'one';
      if (
        i % 10 >= 2 &&
        i % 10 <= 4 &&
        !(i % 100 >= 12 && i % 100 <= 14)
      )
        return 'few';
      if (
        (i !== 1 && i % 10 >= 0 && i % 10 <= 1) ||
        (i % 10 >= 5 && i % 10 <= 9) ||
        (i % 100 >= 12 && i % 100 <= 14)
      )
        return 'many';
      return 'other';
    }

    case 'ja': {
      return 'other';
    }

    default:
      return 'other';
  }
}

function resolveOrdinal(i: number, locale: string): string {
  switch (locale) {
    case 'en': {
      if (i % 10 === 1 && i % 100 !== 11) return 'one';
      if (i % 10 === 2 && i % 100 !== 12) return 'two';
      if (i % 10 === 3 && i % 100 !== 13) return 'few';
      return 'other';
    }

    default:
      return 'other';
  }
}
