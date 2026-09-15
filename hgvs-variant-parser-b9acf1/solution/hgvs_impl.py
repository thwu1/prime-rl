"""HGVS Variant Parser and Formatter - Complete Implementation

Implements parsing, formatting, classification, and grammar validation
of HGVS sequence variant nomenclature expressions.
"""

import copy

# =============================================================================
# Constants & Utilities
# =============================================================================
AA1_TO_AA3 = {
    'A': 'Ala', 'C': 'Cys', 'D': 'Asp', 'E': 'Glu', 'F': 'Phe',
    'G': 'Gly', 'H': 'His', 'I': 'Ile', 'K': 'Lys', 'L': 'Leu',
    'M': 'Met', 'N': 'Asn', 'P': 'Pro', 'Q': 'Gln', 'R': 'Arg',
    'S': 'Ser', 'T': 'Thr', 'V': 'Val', 'W': 'Trp', 'Y': 'Tyr',
    'B': 'Asx', 'Z': 'Glx', 'X': 'Xaa', 'U': 'Sec', '*': 'Ter',
}
AA3_TO_AA1 = {v: k for k, v in AA1_TO_AA3.items()}
AA1_CHARS = set('ACDEFGHIKLMNPQRSTVWYBZXU')
AA3_NAMES = [
    'Ala','Cys','Asp','Glu','Phe','Gly','His','Ile','Lys','Leu',
    'Met','Asn','Pro','Gln','Arg','Ser','Thr','Val','Trp','Tyr',
    'Asx','Glx','Xaa','Sec',
]
DNA_CHARS = set('ACGTRYMKWSBDHVNacgtrymkwsbdhvn')
RNA_CHARS = set('ACGURYMKWSBDHVNacgurymkwsbdhvn')


def aa_to_aa1(s):
    if s is None:
        return None
    if s == '':
        return ''
    result = []
    i = 0
    while i < len(s):
        if i + 3 <= len(s) and s[i:i+3] in AA3_TO_AA1:
            result.append(AA3_TO_AA1[s[i:i+3]])
            i += 3
        elif s[i] in AA1_TO_AA3:
            result.append(s[i])
            i += 1
        else:
            return s
    return ''.join(result)


def aa1_to_aa3(s):
    if s is None:
        return None
    if s == '':
        return ''
    return ''.join(AA1_TO_AA3.get(c, c) for c in s)


class ParseError(Exception):
    pass


# =============================================================================
# Model Classes
# =============================================================================
class SimplePosition:
    def __init__(self, base=None, uncertain=False):
        self.base = base
        self.uncertain = uncertain

    def format(self, conf=None):
        s = '?' if self.base is None else str(self.base)
        return '(' + s + ')' if self.uncertain else s

    def __eq__(self, other):
        if not isinstance(other, SimplePosition):
            return NotImplemented
        return self.base == other.base and self.uncertain == other.uncertain

    @property
    def is_uncertain(self):
        return self.uncertain or self.base is None


class BaseOffsetPosition:
    def __init__(self, base=None, offset=0, datum='CDS_START', uncertain=False):
        self.base = base
        self.offset = offset
        self.datum = datum
        self.uncertain = uncertain

    def _format_pos(self):
        if self.base is None:
            base_str = '?'
        elif self.datum == 'CDS_END':
            base_str = '*' + str(self.base)
        else:
            base_str = str(self.base)
        if self.offset is None:
            offset_str = '+?'
        elif self.offset == 0:
            offset_str = ''
        else:
            offset_str = '%+d' % self.offset
        return base_str + offset_str

    def format(self, conf=None):
        pos = self._format_pos()
        return '(' + pos + ')' if self.uncertain else pos

    @property
    def is_uncertain(self):
        return self.uncertain or self.base is None or self.offset is None

    def __eq__(self, other):
        if not isinstance(other, BaseOffsetPosition):
            return NotImplemented
        return (self.base == other.base and self.offset == other.offset
                and self.datum == other.datum and self.uncertain == other.uncertain)


class AAPosition:
    def __init__(self, base=None, aa=None, uncertain=False):
        self.base = base
        self.aa = aa
        self.uncertain = uncertain

    def format(self, conf=None):
        p_3_letter = True
        p_term_asterisk = False
        if conf:
            if 'p_3_letter' in conf and conf['p_3_letter'] is not None:
                p_3_letter = conf['p_3_letter']
            if 'p_term_asterisk' in conf and conf['p_term_asterisk'] is not None:
                p_term_asterisk = conf['p_term_asterisk']
        pos = '?' if self.base is None else str(self.base)
        if p_3_letter:
            aa = '?' if self.aa is None else aa1_to_aa3(self.aa)
            if p_term_asterisk and aa == 'Ter':
                aa = '*'
        else:
            aa = '?' if self.aa is None else self.aa
        s = aa + pos
        return '(' + s + ')' if self.uncertain else s

    def __eq__(self, other):
        if not isinstance(other, AAPosition):
            return NotImplemented
        return self.base == other.base and self.aa == other.aa and self.uncertain == other.uncertain


class Interval:
    def __init__(self, start=None, end=None, uncertain=False):
        self.start = start
        if end is None and start is not None:
            self.end = copy.deepcopy(start)
        else:
            self.end = end
        self.uncertain = uncertain

    def format(self, conf=None):
        if self.start is None:
            return ''
        if (self.end is None or self.start == self.end) and not self.uncertain:
            return self.start.format(conf)
        iv = self.start.format(conf)
        if self.end != self.start:
            iv = iv + '_' + self.end.format(conf)
        return '(' + iv + ')' if self.uncertain else iv

    def _length(self):
        if self.end is None:
            return 1
        return self.end.base - self.start.base + 1


class BaseOffsetInterval(Interval):
    def __init__(self, start=None, end=None, uncertain=False):
        if end is None and start is not None:
            end = copy.deepcopy(start)
        if start is not None and end is not None:
            if start.datum == 'CDS_END':
                end.datum = 'CDS_END'
        self.start = start
        self.end = end
        self.uncertain = uncertain

    def format(self, conf=None):
        if self.start is None:
            return ''
        if self.end is None or self.start == self.end:
            return self.start.format(conf)
        s = self.start._format_pos()
        if self.start.is_uncertain and self.start.base is not None:
            s_str = '(?_' + s + ')'
        else:
            s_str = s
        e = self.end._format_pos()
        if self.end.is_uncertain and self.end.base is not None:
            e_str = '(' + e + '_?)'
        else:
            e_str = e
        iv = s_str + '_' + e_str
        return '(' + iv + ')' if self.uncertain else iv


# --- Edit classes ---

class NARefAlt:
    def __init__(self, ref=None, alt=None, uncertain=False):
        self.ref = ref
        self.alt = alt
        self.uncertain = uncertain

    @property
    def ref_s(self):
        return (self.ref if (isinstance(self.ref, str) and self.ref
                            and self.ref[0] in 'ACGTUNacgtun') else None)

    @property
    def ref_n(self):
        try:
            return int(self.ref)
        except (ValueError, TypeError):
            return len(self.ref) if self.ref else None

    @property
    def type(self):
        if self.ref is not None and self.alt is not None:
            if self.ref == self.alt:
                return 'identity'
            elif len(self.alt) == 1 and len(self.ref) == 1 and not self.ref.isdigit():
                return 'sub'
            else:
                return 'delins'
        elif self.ref is not None:
            return 'del'
        else:
            return 'ins'

    def format(self, conf=None):
        if self.ref is None and self.alt is None:
            raise ValueError("ref and alt both undefined")
        max_ref_length = 0
        if conf and 'max_ref_length' in conf:
            max_ref_length = conf['max_ref_length']
        if max_ref_length is not None:
            ref = self.ref_s
            if ref is None or len(ref) > max_ref_length:
                ref = ''
        else:
            ref = self.ref if self.ref else ''
        if self.ref is not None and self.alt is not None:
            if self.ref == self.alt:
                s = ref + '='
            elif len(self.alt) == 1 and len(self.ref) == 1 and not self.ref.isdigit():
                s = self.ref + '>' + self.alt
            else:
                s = 'del' + ref + 'ins' + self.alt
        elif self.ref is not None:
            s = 'del' + ref
        else:
            s = 'ins' + self.alt
        return '(' + s + ')' if self.uncertain else s


class AARefAlt:
    def __init__(self, ref=None, alt=None, uncertain=False):
        self.ref = aa_to_aa1(ref) if ref is not None else None
        self.alt = aa_to_aa1(alt) if alt is not None else None
        self.uncertain = uncertain

    @property
    def type(self):
        if self.ref is not None and self.alt is not None:
            if self.ref == self.alt:
                return 'identity'
            elif len(self.ref) >= 1 and len(self.alt) == 1 and len(self.ref) == 1:
                return 'sub'
            else:
                return 'delins'
        elif self.ref is not None and self.alt is None:
            return 'del'
        elif self.ref is None and self.alt is not None:
            return 'ins'
        return 'identity'

    def format(self, conf=None):
        if self.ref is None and self.alt is None:
            return '='
        p_3_letter, p_term_asterisk = True, False
        if conf:
            if 'p_3_letter' in conf and conf['p_3_letter'] is not None:
                p_3_letter = conf['p_3_letter']
            if 'p_term_asterisk' in conf and conf['p_term_asterisk'] is not None:
                p_term_asterisk = conf['p_term_asterisk']
        if self.ref is not None and self.alt is not None:
            if self.ref == self.alt:
                if p_3_letter:
                    s = aa1_to_aa3(self.ref) + '='
                    if p_term_asterisk and s == 'Ter=':
                        s = '*='
                else:
                    s = self.ref + '='
            elif len(self.ref) == 1 and len(self.alt) == 1:
                if p_3_letter:
                    s = aa1_to_aa3(self.alt)
                    if p_term_asterisk and s == 'Ter':
                        s = '*'
                else:
                    s = self.alt
            else:
                if p_3_letter:
                    s = 'delins' + aa1_to_aa3(self.alt)
                else:
                    s = 'delins' + self.alt
        elif self.ref is not None and self.alt is None:
            s = 'del'
        elif self.ref is None and self.alt is not None:
            if p_3_letter:
                s = 'ins' + aa1_to_aa3(self.alt)
            else:
                s = 'ins' + self.alt
        else:
            raise RuntimeError("Unreachable")
        return '(' + s + ')' if self.uncertain else s


class AASub:
    def __init__(self, ref='', alt=None, uncertain=False):
        self.ref = aa_to_aa1(ref)
        self.alt = aa_to_aa1(alt) if alt else alt
        self.uncertain = uncertain

    @property
    def type(self):
        return 'sub'

    def format(self, conf=None):
        p_3_letter, p_term_asterisk = True, False
        if conf:
            if 'p_3_letter' in conf and conf['p_3_letter'] is not None:
                p_3_letter = conf['p_3_letter']
            if 'p_term_asterisk' in conf and conf['p_term_asterisk'] is not None:
                p_term_asterisk = conf['p_term_asterisk']
        if p_3_letter:
            s = aa1_to_aa3(self.alt) if self.alt != '?' else self.alt
            if p_term_asterisk and s == 'Ter':
                s = '*'
        else:
            s = self.alt
        return '(' + s + ')' if self.uncertain else s


class AAFs:
    def __init__(self, ref='', alt=None, length=None, uncertain=False):
        self.ref = aa_to_aa1(ref)
        self.alt = aa_to_aa1(alt) if alt else (alt if alt is None else '')
        self.length = length
        self.uncertain = uncertain

    @property
    def type(self):
        return 'fs'

    def format(self, conf=None):
        p_3_letter, p_term_asterisk = True, False
        if conf:
            if 'p_3_letter' in conf and conf['p_3_letter'] is not None:
                p_3_letter = conf['p_3_letter']
            if 'p_term_asterisk' in conf and conf['p_term_asterisk'] is not None:
                p_term_asterisk = conf['p_term_asterisk']
        st_length = str(self.length) if self.length is not None else ''
        alt_str = self.alt if self.alt else ''
        if p_3_letter:
            alt_fmt = aa1_to_aa3(alt_str)
            if p_term_asterisk:
                s = alt_fmt + 'fs*' + st_length
            else:
                s = alt_fmt + 'fsTer' + st_length
        else:
            s = alt_str + 'fs*' + st_length
        return '(' + s + ')' if self.uncertain else s


class AAExt:
    def __init__(self, ref='', alt=None, aaterm=None, length=None, uncertain=False):
        self.ref = aa_to_aa1(ref)
        self.alt = aa_to_aa1(alt)
        self.aaterm = aa_to_aa1(aaterm)
        self.length = length
        self.uncertain = uncertain

    @property
    def type(self):
        return 'ext'

    def format(self, conf=None):
        p_3_letter, p_term_asterisk = True, False
        if conf:
            if 'p_3_letter' in conf and conf['p_3_letter'] is not None:
                p_3_letter = conf['p_3_letter']
            if 'p_term_asterisk' in conf and conf['p_term_asterisk'] is not None:
                p_term_asterisk = conf['p_term_asterisk']
        st_alt = self.alt or ''
        st_aaterm = self.aaterm or ''
        st_length = str(self.length) if self.length is not None else ''
        if p_3_letter:
            st_alt = aa1_to_aa3(st_alt)
            st_aaterm = aa1_to_aa3(st_aaterm)
            if p_term_asterisk and st_alt == 'Ter':
                st_alt = '*'
            if p_term_asterisk and st_aaterm == 'Ter':
                st_aaterm = '*'
        s = st_alt + 'ext' + st_aaterm + st_length
        return '(' + s + ')' if self.uncertain else s


class Dup:
    def __init__(self, ref=None, uncertain=False):
        self.ref = ref
        self.uncertain = uncertain

    @property
    def ref_s(self):
        return (self.ref if (isinstance(self.ref, str) and self.ref
                            and self.ref[0] in 'ACGTUNacgtun') else None)

    @property
    def type(self):
        return 'dup'

    def format(self, conf=None):
        max_ref_length = 0
        if conf and 'max_ref_length' in conf:
            max_ref_length = conf['max_ref_length']
        if max_ref_length is not None:
            ref = self.ref_s
            if ref is None or len(ref) > max_ref_length:
                ref = ''
        else:
            ref = self.ref
        return 'dup' + (ref or '')


class Inv:
    def __init__(self, ref=None, uncertain=False):
        self.ref = ref
        self.uncertain = uncertain

    @property
    def type(self):
        return 'inv'

    def format(self, conf=None):
        return 'inv'


class NACopy:
    def __init__(self, copy_num=None, uncertain=False):
        self.copy = copy_num
        self.uncertain = uncertain

    @property
    def type(self):
        return 'copy'

    def format(self, conf=None):
        s = 'copy' + str(self.copy)
        return '(' + s + ')' if self.uncertain else s


class Conv:
    def __init__(self, from_ac=None, from_type=None, from_pos=None, uncertain=False):
        self.from_ac = from_ac
        self.from_type = from_type
        self.from_pos = from_pos
        self.uncertain = uncertain

    @property
    def type(self):
        return 'con'

    def format(self, conf=None):
        if self.from_ac and self.from_type and self.from_pos:
            s = 'con' + self.from_ac + ':' + self.from_type + '.' + self.from_pos.format(conf)
        else:
            s = 'con'
        return '(' + s + ')' if self.uncertain else s


class PosEdit:
    def __init__(self, pos=None, edit=None, uncertain=False):
        self.pos = pos
        self.edit = edit
        self.uncertain = uncertain

    def format(self, conf=None):
        if self.pos is None:
            if isinstance(self.edit, str):
                rv = self.edit
            elif self.edit is not None:
                rv = self.edit.format(conf)
            else:
                rv = ''
        else:
            edit_str = self.edit.format(conf) if not isinstance(self.edit, str) else self.edit
            rv = self.pos.format(conf) + edit_str
        if self.uncertain:
            if isinstance(self.edit, str) and self.edit in ('0', ''):
                rv = rv + '?'
            else:
                rv = '(' + rv + ')'
        return rv


class SequenceVariant:
    def __init__(self, ac=None, type_=None, posedit=None, gene=None):
        self.ac = ac
        self.type = type_
        self.posedit = posedit
        self.gene = gene

    def format(self, conf=None):
        if self.ac:
            ref = self.ac
            if self.gene:
                ref += '(' + self.gene + ')'
            ref += ':'
        else:
            ref = ''
        if self.posedit is not None:
            posedit = self.posedit.format(conf)
        else:
            posedit = '?'
        return ref + self.type + '.' + posedit


# =============================================================================
# Parser
# =============================================================================
class Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def remaining(self):
        return self.text[self.pos:]

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else None

    def advance(self, n=1):
        result = self.text[self.pos:self.pos + n]
        self.pos += n
        return result

    def at_end(self):
        return self.pos >= len(self.text)

    def expect(self, s):
        if self.text[self.pos:self.pos + len(s)] != s:
            raise ParseError(f"Expected '{s}' at {self.pos}")
        self.pos += len(s)

    def try_match(self, s):
        if self.text[self.pos:self.pos + len(s)] == s:
            self.pos += len(s)
            return True
        return False

    def save(self):
        return self.pos

    def restore(self, p):
        self.pos = p

    # --- Accession ---
    def parse_accn(self):
        start = self.pos
        if self.at_end() or not self.peek().isalpha():
            raise ParseError("Expected letter for accession")
        self.advance()
        while not self.at_end():
            c = self.peek()
            if c.isalnum():
                self.advance()
            elif c in '-_':
                if self.pos + 1 < len(self.text) and self.text[self.pos + 1].isalnum():
                    self.advance()
                else:
                    break
            else:
                break
        if not self.at_end() and self.peek() == '.':
            sv = self.save()
            self.advance()
            if not self.at_end() and self.peek().isdigit():
                while not self.at_end() and self.peek().isdigit():
                    self.advance()
            else:
                self.restore(sv)
        return self.text[start:self.pos]

    def parse_opt_gene(self):
        if not self.at_end() and self.peek() == '(':
            sv = self.save()
            try:
                self.expect('(')
                gene = self.parse_gene_symbol()
                self.expect(')')
                return gene
            except ParseError:
                self.restore(sv)
        return None

    def parse_gene_symbol(self):
        start = self.pos
        if self.at_end() or not self.peek().isalpha():
            raise ParseError("Expected letter for gene")
        self.advance()
        while not self.at_end():
            c = self.peek()
            if c.isalnum():
                self.advance()
            elif c in '-_':
                if self.pos + 1 < len(self.text) and self.text[self.pos + 1].isalnum():
                    self.advance()
                else:
                    break
            else:
                break
        return self.text[start:self.pos]

    # --- Numbers ---
    def parse_num(self):
        start = self.pos
        if self.at_end() or not self.peek().isdigit():
            raise ParseError("Expected digit")
        while not self.at_end() and self.peek().isdigit():
            self.advance()
        return int(self.text[start:self.pos])

    def parse_snum(self):
        start = self.pos
        if not self.at_end() and self.peek() in '+-':
            self.advance()
        if self.at_end() or not self.peek().isdigit():
            raise ParseError("Expected digit in snum")
        while not self.at_end() and self.peek().isdigit():
            self.advance()
        return int(self.text[start:self.pos])

    def parse_base(self):
        return self.parse_snum()

    def parse_offset(self):
        if not self.at_end() and self.peek() in '+-':
            return self.parse_snum()
        return 0

    # --- DNA/RNA ---
    def parse_dna_char(self):
        if not self.at_end() and self.peek() in DNA_CHARS:
            return self.advance()
        return None

    def parse_dna_seq(self, min_len=0):
        start = self.pos
        while not self.at_end() and self.peek() in DNA_CHARS:
            self.advance()
        result = self.text[start:self.pos]
        if len(result) < min_len:
            self.pos = start
            raise ParseError("DNA seq too short")
        return result

    def parse_rna_char(self):
        if not self.at_end() and self.peek() in RNA_CHARS:
            return self.advance()
        return None

    def parse_rna_seq(self, min_len=0):
        start = self.pos
        while not self.at_end() and self.peek() in RNA_CHARS:
            self.advance()
        result = self.text[start:self.pos]
        if len(result) < min_len:
            self.pos = start
            raise ParseError("RNA seq too short")
        return result

    # --- Amino acids ---
    def try_aa3(self):
        if self.pos + 3 <= len(self.text):
            t = self.text[self.pos:self.pos + 3]
            if t in AA3_TO_AA1:
                self.pos += 3
                return t
        return None

    def try_term3(self):
        if self.text[self.pos:self.pos + 3] == 'Ter':
            self.pos += 3
            return 'Ter'
        return None

    def try_term1(self):
        if not self.at_end() and self.peek() in 'X*':
            return self.advance()
        return None

    def try_term13(self):
        t = self.try_term3()
        return t if t else self.try_term1()

    def try_aa1(self):
        if not self.at_end() and self.peek() in AA1_CHARS:
            return self.advance()
        return None

    def try_aa13(self):
        t = self.try_aa3()
        return t if t else self.try_aa1()

    def try_aat13(self):
        t = self.try_term13()
        return t if t else self.try_aa13()

    def parse_aat13_seq(self):
        """Parse sequence of AAs possibly ending with terminator."""
        sv = self.save()
        # Try 3-letter
        result = ''
        found = False
        while True:
            t = self.try_term3()
            if t:
                result += t
                found = True
                break
            a = self.try_aa3()
            if a:
                result += a
                found = True
            else:
                break
        if found and result:
            return result
        self.restore(sv)
        # Try 1-letter
        result = ''
        found = False
        while True:
            t = self.try_term1()
            if t:
                result += t
                found = True
                break
            a = self.try_aa1()
            if a:
                result += a
                found = True
            else:
                break
        if found and result:
            return result
        raise ParseError("Expected AA sequence")

    # --- Positions ---
    def parse_def_g_pos(self):
        if not self.at_end() and self.peek() == '?':
            self.advance()
            return SimplePosition(base=None)
        return SimplePosition(base=self.parse_num())

    parse_def_m_pos = parse_def_g_pos

    def parse_def_c_pos(self):
        if not self.at_end() and self.peek() == '*':
            self.advance()
            b = self.parse_num()
            o = self.parse_offset()
            return BaseOffsetPosition(base=b, offset=o, datum='CDS_END')
        b = self.parse_base()
        o = self.parse_offset()
        return BaseOffsetPosition(base=b, offset=o, datum='CDS_START')

    def parse_def_n_pos(self):
        b = self.parse_base()
        o = self.parse_offset()
        return BaseOffsetPosition(base=b, offset=o, datum='SEQ_START')

    parse_def_r_pos = parse_def_n_pos

    def parse_def_p_pos(self):
        t = self.try_term13()
        if t:
            aa = aa_to_aa1(t)
            p = self.parse_num()
            return AAPosition(base=p, aa=aa)
        a = self.try_aa13()
        if a:
            aa = aa_to_aa1(a)
            p = self.parse_num()
            return AAPosition(base=p, aa=aa)
        raise ParseError("Expected AA for p_pos")

    # --- Intervals ---
    def parse_def_g_interval(self):
        start = self.parse_def_g_pos()
        if not self.at_end() and self.peek() == '_':
            self.advance()
            end = self.parse_def_g_pos()
            return Interval(start=start, end=end)
        return Interval(start=start)

    def parse_g_interval(self):
        sv = self.save()
        try:
            return self._parse_uncertain_g_interval()
        except ParseError:
            self.restore(sv)
        return self.parse_def_g_interval()

    def _parse_uncertain_g_interval(self):
        if self.peek() != '(':
            raise ParseError("Expected (")
        self.advance()
        iv_start = self.parse_def_g_interval()
        self.expect(')')
        if not self.at_end() and self.peek() == '_':
            self.advance()
            if not self.at_end() and self.peek() == '(':
                self.advance()
                iv_end = self.parse_def_g_interval()
                self.expect(')')
                iv_start.uncertain = True
                iv_end.uncertain = True
                return Interval(start=iv_start, end=iv_end)
            else:
                iv_end = self.parse_def_g_interval()
                iv_start.uncertain = True
                return Interval(start=iv_start, end=iv_end)
        else:
            iv_start.uncertain = True
            return iv_start

    def _parse_simple_interval(self, pos_fn, interval_cls=Interval):
        start = pos_fn()
        if not self.at_end() and self.peek() == '_':
            self.advance()
            end = pos_fn()
            return interval_cls(start=start, end=end)
        return interval_cls(start=start)

    def _parse_maybe_uncertain_interval(self, pos_fn, interval_cls=Interval):
        if not self.at_end() and self.peek() == '(':
            self.advance()
            iv = self._parse_simple_interval(pos_fn, interval_cls)
            self.expect(')')
            iv.uncertain = True
            return iv
        return self._parse_simple_interval(pos_fn, interval_cls)

    def parse_m_interval(self):
        return self._parse_maybe_uncertain_interval(self.parse_def_m_pos)

    def parse_c_interval(self):
        return self._parse_maybe_uncertain_interval(self.parse_def_c_pos, BaseOffsetInterval)

    def parse_n_interval(self):
        return self._parse_maybe_uncertain_interval(self.parse_def_n_pos, BaseOffsetInterval)

    def parse_r_interval(self):
        return self._parse_maybe_uncertain_interval(self.parse_def_r_pos, BaseOffsetInterval)

    def parse_p_interval(self):
        return self._parse_maybe_uncertain_interval(self.parse_def_p_pos)

    # --- DNA Edits ---
    def parse_dna_edit(self):
        # 1. identity: dna* =
        sv = self.save()
        ref = self.parse_dna_seq(0)
        if not self.at_end() and self.peek() == '=':
            self.advance()
            return NARefAlt(ref=ref, alt=ref)
        self.restore(sv)

        # 2. subst: dna > dna
        sv = self.save()
        rc = self.parse_dna_char()
        if rc and not self.at_end() and self.peek() == '>':
            self.advance()
            ac = self.parse_dna_char()
            if ac:
                return NARefAlt(ref=rc, alt=ac)
        self.restore(sv)

        # 3/4. del[ins] or del
        sv = self.save()
        if self.try_match('del'):
            ref_sv = self.pos
            try:
                ref_val = str(self.parse_num())
            except ParseError:
                self.pos = ref_sv
                ref_val = self.parse_dna_seq(0)
            ins_sv = self.save()
            if self.try_match('ins'):
                try:
                    alt_val = self.parse_dna_seq(1)
                    return NARefAlt(ref=ref_val, alt=alt_val)
                except ParseError:
                    self.restore(ins_sv)
            return NARefAlt(ref=ref_val, alt=None)
        self.restore(sv)

        # 5. ins
        sv = self.save()
        if self.try_match('ins'):
            alt_val = self.parse_dna_seq(1)
            return NARefAlt(ref=None, alt=alt_val)
        self.restore(sv)

        # 6. dup
        sv = self.save()
        if self.try_match('dup'):
            ref_val = self.parse_dna_seq(0)
            return Dup(ref=ref_val)
        self.restore(sv)

        # 7. inv
        sv = self.save()
        if self.try_match('inv'):
            ref_sv = self.pos
            try:
                str(self.parse_num())
            except ParseError:
                self.pos = ref_sv
                self.parse_dna_seq(0)
            return Inv(ref=None)
        self.restore(sv)

        # 8. copy
        sv = self.save()
        if self.try_match('copy'):
            n = self.parse_num()
            return NACopy(copy_num=n)
        self.restore(sv)

        # 9. con
        sv = self.save()
        if self.try_match('con'):
            ac = self.parse_accn()
            self.expect(':')
            vt = self.advance()
            self.expect('.')
            if vt in ('g', 'm'):
                pos = self.parse_def_g_interval()
            elif vt == 'c':
                pos = self._parse_simple_interval(self.parse_def_c_pos, BaseOffsetInterval)
            else:
                pos = self._parse_simple_interval(self.parse_def_n_pos, BaseOffsetInterval)
            return Conv(from_ac=ac, from_type=vt, from_pos=pos)
        self.restore(sv)

        raise ParseError("Expected DNA edit")

    def parse_rna_edit(self):
        # identity
        sv = self.save()
        ref = self.parse_rna_seq(0)
        if not self.at_end() and self.peek() == '=':
            self.advance()
            return NARefAlt(ref=ref, alt=ref)
        self.restore(sv)

        # subst
        sv = self.save()
        rc = self.parse_rna_char()
        if rc and not self.at_end() and self.peek() == '>':
            self.advance()
            ac = self.parse_rna_char()
            if ac:
                return NARefAlt(ref=rc, alt=ac)
        self.restore(sv)

        # del[ins] or del
        sv = self.save()
        if self.try_match('del'):
            ref_sv = self.pos
            try:
                ref_val = str(self.parse_num())
            except ParseError:
                self.pos = ref_sv
                ref_val = self.parse_rna_seq(0)
            ins_sv = self.save()
            if self.try_match('ins'):
                try:
                    alt_val = self.parse_rna_seq(1)
                    return NARefAlt(ref=ref_val, alt=alt_val)
                except ParseError:
                    self.restore(ins_sv)
            return NARefAlt(ref=ref_val, alt=None)
        self.restore(sv)

        # ins
        sv = self.save()
        if self.try_match('ins'):
            alt_val = self.parse_rna_seq(1)
            return NARefAlt(ref=None, alt=alt_val)
        self.restore(sv)

        # dup
        sv = self.save()
        if self.try_match('dup'):
            ref_val = self.parse_rna_seq(0)
            return Dup(ref=ref_val)
        self.restore(sv)

        # inv
        sv = self.save()
        if self.try_match('inv'):
            ref_sv = self.pos
            try:
                str(self.parse_num())
            except ParseError:
                self.pos = ref_sv
                self.parse_rna_seq(0)
            return Inv(ref=None)
        self.restore(sv)

        raise ParseError("Expected RNA edit")

    # --- Protein Edits ---
    def parse_pro_edit(self):
        # Try fs
        sv = self.save()
        try:
            return self._parse_pro_fs()
        except ParseError:
            self.restore(sv)

        # Try ext
        sv = self.save()
        try:
            return self._parse_pro_ext()
        except ParseError:
            self.restore(sv)

        # Try subst: (aat13 | ?)
        sv = self.save()
        if not self.at_end() and self.peek() == '?':
            self.advance()
            if self.at_end():
                return AASub(ref='', alt='?')
            self.restore(sv)

        sv = self.save()
        t = self.try_aat13()
        if t is not None:
            # Check it's not followed by 'fs' or 'ext'
            rem = self.remaining()
            if not rem.startswith('fs') and not rem.startswith('ext'):
                aa1 = aa_to_aa1(t)
                return AASub(ref='', alt=aa1)
        self.restore(sv)

        # Try delins
        sv = self.save()
        if self.try_match('delins'):
            alt = self.parse_aat13_seq()
            return AARefAlt(ref='', alt=alt)
        self.restore(sv)

        # Try del
        sv = self.save()
        if self.try_match('del'):
            if self.at_end() or self.peek() not in AA1_CHARS:
                return AARefAlt(ref='', alt=None)
            self.restore(sv)
        else:
            self.restore(sv)

        # Try ins
        sv = self.save()
        if self.try_match('ins'):
            alt = self.parse_aat13_seq()
            return AARefAlt(ref=None, alt=alt)
        self.restore(sv)

        # Try dup
        sv = self.save()
        if self.try_match('dup'):
            if self.at_end():
                return Dup(ref='')
            self.restore(sv)
        else:
            self.restore(sv)

        # Try ident =
        if not self.at_end() and self.peek() == '=':
            self.advance()
            return AARefAlt(ref='', alt='')

        raise ParseError("Expected protein edit")

    def _parse_pro_fs(self):
        sv = self.save()
        # (aat13 | empty) fs (term13 offset | nothing)
        alt = self.try_aat13()
        if alt is None:
            alt = ''
        if not self.try_match('fs'):
            raise ParseError("Expected 'fs'")
        length = None
        t = self.try_term13()
        if t:
            length = self._parse_fsext_offset()
        return AAFs(ref='', alt=alt, length=length)

    def _parse_pro_ext(self):
        sv = self.save()
        alt = self.try_aat13()
        if not self.try_match('ext'):
            raise ParseError("Expected 'ext'")
        aaterm, length = self._parse_aa13_ext_body()
        aa1_alt = aa_to_aa1(alt) if alt else None
        aa1_aaterm = aa_to_aa1(aaterm) if aaterm else None
        return AAExt(ref='', alt=aa1_alt, aaterm=aa1_aaterm, length=length)

    def _parse_aa13_ext_body(self):
        # Try term13 fsext_offset
        sv = self.save()
        t = self.try_term13()
        if t:
            length = self._parse_fsext_offset()
            return (t, length)
        # Try (aa13 | nothing) nnum
        sv2 = self.save()
        a = self.try_aa13()
        if not self.at_end() and self.peek() == '-':
            self.advance()
            try:
                n = self.parse_num()
                return (a, -n)
            except ParseError:
                self.restore(sv2)
        elif a is not None:
            self.restore(sv2)
        # Nothing
        if not self.at_end() and self.peek() == '-':
            self.advance()
            try:
                n = self.parse_num()
                return (None, -n)
            except ParseError:
                pass
        return (None, None)

    def _parse_fsext_offset(self):
        if not self.at_end() and self.peek().isdigit():
            return self.parse_num()
        if not self.at_end() and self.peek() == '?':
            self.advance()
            return '?'
        return None

    # --- PosEdits ---
    def parse_c_posedit(self):
        pos = self.parse_c_interval()
        edit = self.parse_dna_edit()
        return PosEdit(pos=pos, edit=edit)

    def parse_g_posedit(self):
        pos = self.parse_g_interval()
        edit = self.parse_dna_edit()
        return PosEdit(pos=pos, edit=edit)

    def parse_m_posedit(self):
        pos = self.parse_m_interval()
        edit = self.parse_dna_edit()
        return PosEdit(pos=pos, edit=edit)

    def parse_n_posedit(self):
        pos = self.parse_n_interval()
        edit = self.parse_dna_edit()
        return PosEdit(pos=pos, edit=edit)

    def parse_r_posedit(self):
        sv = self.save()
        if not self.at_end() and self.peek() == '(':
            self.advance()
            try:
                pos = self.parse_r_interval()
                edit = self.parse_rna_edit()
                self.expect(')')
                return PosEdit(pos=pos, edit=edit, uncertain=True)
            except ParseError:
                self.restore(sv)
        pos = self.parse_r_interval()
        edit = self.parse_rna_edit()
        return PosEdit(pos=pos, edit=edit)

    def parse_p_posedit(self):
        # Try special first
        sv = self.save()
        try:
            result = self._parse_p_posedit_special()
            return result
        except ParseError:
            self.restore(sv)

        # Try uncertain (pos edit)
        sv = self.save()
        if not self.at_end() and self.peek() == '(':
            self.advance()
            try:
                pos = self.parse_p_interval()
                edit = self.parse_pro_edit()
                self.expect(')')
                return PosEdit(pos=pos, edit=edit, uncertain=True)
            except ParseError:
                self.restore(sv)

        # Try normal
        pos = self.parse_p_interval()
        edit = self.parse_pro_edit()
        return PosEdit(pos=pos, edit=edit)

    def _parse_p_posedit_special(self):
        if self.at_end():
            raise ParseError("Empty")
        c = self.peek()
        if c == '?':
            self.advance()
            return None
        if c == '(':
            self.advance()
            if not self.at_end() and self.peek() == '=':
                self.advance()
                self.expect(')')
                return PosEdit(pos=None, edit='=', uncertain=True)
            raise ParseError("Expected =)")
        if c == '=':
            self.advance()
            return PosEdit(pos=None, edit='=')
        if c == '0':
            self.advance()
            if not self.at_end() and self.peek() == '?':
                self.advance()
                return PosEdit(pos=None, edit='0', uncertain=True)
            return PosEdit(pos=None, edit='0')
        raise ParseError("Not special p_posedit")

    # --- Variant ---
    def parse_variant(self):
        ac = self.parse_accn()
        gene = self.parse_opt_gene()
        self.expect(':')
        vtype = self.advance()
        if vtype not in 'cgmnrp':
            raise ParseError(f"Invalid type: {vtype}")
        self.expect('.')
        posedit = self._parse_posedit_for_type(vtype)
        if not self.at_end():
            raise ParseError(f"Trailing: {self.remaining()}")
        return SequenceVariant(ac=ac, type_=vtype, posedit=posedit, gene=gene)

    def _parse_posedit_for_type(self, vtype):
        dispatch = {
            'c': self.parse_c_posedit,
            'g': self.parse_g_posedit,
            'm': self.parse_m_posedit,
            'n': self.parse_n_posedit,
            'r': self.parse_r_posedit,
            'p': self.parse_p_posedit,
        }
        return dispatch[vtype]()

    def parse_typed_variant(self, vtype):
        """Parse a variant expecting a specific type prefix."""
        ac = self.parse_accn()
        gene = self.parse_opt_gene()
        self.expect(':')
        actual_type = self.advance()
        if actual_type != vtype:
            raise ParseError(f"Expected type '{vtype}', got '{actual_type}'")
        self.expect('.')
        posedit = self._parse_posedit_for_type(vtype)
        if not self.at_end():
            raise ParseError(f"Trailing: {self.remaining()}")
        return SequenceVariant(ac=ac, type_=actual_type, posedit=posedit, gene=gene)


# =============================================================================
# Public API
# =============================================================================
def parse(s):
    p = Parser(s)
    return p.parse_variant()


def format_variant(parsed, conf=None):
    return parsed.format(conf)


def roundtrip(s):
    return format_variant(parse(s))


def classify_edit(s):
    v = parse(s)
    if v.posedit is None:
        return None
    if isinstance(v.posedit, PosEdit):
        if isinstance(v.posedit.edit, str):
            if v.posedit.edit == '=':
                return 'identity'
            return v.posedit.edit
        return v.posedit.edit.type
    return None


def validate_grammar(rule, input_str):
    try:
        p = Parser(input_str)
        _dispatch_rule(p, rule)
        return p.at_end()
    except (ParseError, Exception):
        return False


def _dispatch_rule(p, rule):
    rules = {
        'accn': p.parse_accn,
        'num': p.parse_num,
        'snum': p.parse_snum,
        'base': p.parse_base,
        'offset': p.parse_offset,
        'hgvs_variant': p.parse_variant,
    }
    if rule in rules:
        rules[rule]()
        return

    # Typed variants
    type_map = {'c_variant': 'c', 'g_variant': 'g', 'm_variant': 'm',
                'n_variant': 'n', 'r_variant': 'r', 'p_variant': 'p'}
    if rule in type_map:
        p.parse_typed_variant(type_map[rule])
        return

    # Single-char rules
    if rule == 'dna':
        c = p.parse_dna_char()
        if c is None:
            raise ParseError("Invalid dna")
        return
    if rule == 'rna':
        c = p.parse_rna_char()
        if c is None:
            raise ParseError("Invalid rna")
        return
    if rule == 'aa1':
        c = p.try_aa1()
        if c is None:
            raise ParseError("Invalid aa1")
        return
    if rule == 'aa3':
        c = p.try_aa3()
        if c is None:
            raise ParseError("Invalid aa3")
        return
    if rule == 'aa13':
        c = p.try_aa13()
        if c is None:
            raise ParseError("Invalid aa13")
        return
    if rule == 'term1':
        c = p.try_term1()
        if c is None:
            raise ParseError("Invalid term1")
        return
    if rule == 'term3':
        c = p.try_term3()
        if c is None:
            raise ParseError("Invalid term3")
        return
    if rule == 'term13':
        c = p.try_term13()
        if c is None:
            raise ParseError("Invalid term13")
        return

    # Edit rules
    if rule == 'dna_edit':
        p.parse_dna_edit()
        return
    if rule == 'rna_edit':
        p.parse_rna_edit()
        return
    if rule == 'pro_edit':
        p.parse_pro_edit()
        return

    raise ParseError(f"Unknown rule: {rule}")
