
"""
Isabelle/HOL theory file parser.

Extracts structured information from .thy files: theory name, imports,
datatypes, function definitions, lemma/theorem names, and locales.
"""

import re


class IsabelleParser:
    """Parser for Isabelle/HOL .thy theory files."""

    # Isabelle keywords that should never be treated as definition/lemma names
    _KEYWORDS = frozenset({
        'where', 'is', 'and', 'if', 'then', 'else', 'case', 'of', 'let', 'in',
        'for', 'do', 'shows', 'assumes', 'fixes', 'begin', 'end', 'proof', 'qed',
        'using', 'by', 'simp', 'auto', 'rule', 'intro', 'elim', 'obtains',
        'True', 'False', 'None', 'Some', 'have', 'from', 'with', 'note', 'show',
        'next', 'done', 'apply', 'that', 'this', 'moreover', 'ultimately',
        'hence', 'thus', 'also', 'finally', 'supply', 'unfolding', 'sorry',
        'oops', 'defer', 'prefer', 'back', 'declare', 'method', 'print',
    })

    def parse(self, filepath):
        """Parse an Isabelle .thy file and return structured data."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        content = self._strip_comments(content)

        return {
            'theory_name': self._extract_theory_name(content),
            'imports': self._extract_imports(content),
            'datatypes': self._extract_datatypes(content),
            'functions': self._extract_functions(content),
            'lemmas': self._extract_lemmas(content),
            'locales': self._extract_locales(content),
        }

    # ------------------------------------------------------------------
    # Comment stripping
    # ------------------------------------------------------------------

    def _strip_comments(self, text):
        """Remove nested (* ... *) comments while preserving structure."""
        result = []
        i = 0
        depth = 0
        n = len(text)
        while i < n:
            if i + 1 < n and text[i] == '(' and text[i + 1] == '*':
                depth += 1
                i += 2
            elif i + 1 < n and text[i] == '*' and text[i + 1] == ')':
                if depth > 0:
                    depth -= 1
                i += 2
            elif depth == 0:
                result.append(text[i])
                i += 1
            else:
                i += 1
        return ''.join(result)

    # ------------------------------------------------------------------
    # Theory header
    # ------------------------------------------------------------------

    def _extract_theory_name(self, content):
        m = re.search(r'\btheory\s+(\w+)', content)
        return m.group(1) if m else ''

    def _extract_imports(self, content):
        m = re.search(r'\bimports\s+(.*?)\bbegin\b', content, re.DOTALL)
        if not m:
            return []
        text = m.group(1)
        # Match word-like tokens that may include dots (e.g. Collections.Refine_Dflt_ICF)
        # but skip type variables ('a, 'b, …)
        tokens = re.findall(r"[A-Za-z_][\w.]*", text)
        return tokens

    # ------------------------------------------------------------------
    # Datatype declarations
    # ------------------------------------------------------------------

    def _extract_datatypes(self, content):
        results = []
        # We search for 'datatype ... name = ... | ...'
        # The name is the last word token before '='
        for m in re.finditer(
            r'\bdatatype\b([^=]*?)(\w+)\s*=\s*([^\n]+)',
            content
        ):
            name = m.group(2)
            rhs_first_line = m.group(3)
            # Gather continuation lines that are part of the same declaration
            rhs = rhs_first_line
            # Extract constructors: first identifier in each |-separated alternative
            parts = rhs.split('|')
            constructors = []
            for part in parts:
                part = part.strip()
                cm = re.match(r'(\w+)', part)
                if cm:
                    constructors.append(cm.group(1))
            results.append({'name': name, 'constructors': constructors})
        return results

    # ------------------------------------------------------------------
    # Function / definition declarations
    # ------------------------------------------------------------------

    def _extract_functions(self, content):
        results = []
        seen = set()

        for kind in ['primrec', 'fun', 'definition', 'inductive']:
            # Pattern 1: keyword name :: "type" where  OR  keyword name where
            for m in re.finditer(
                rf'\b{kind}\b\s+([a-zA-Z_]\w*)',
                content
            ):
                name = m.group(1)
                if name in self._KEYWORDS or name in seen:
                    continue
                seen.add(name)
                results.append({'name': name, 'kind': kind})

            # Pattern 2 (definition only): definition "name ..."
            if kind == 'definition':
                for m in re.finditer(
                    r'\bdefinition\b\s+"([a-zA-Z_]\w*)',
                    content
                ):
                    name = m.group(1)
                    if name in self._KEYWORDS or name in seen:
                        continue
                    seen.add(name)
                    results.append({'name': name, 'kind': 'definition'})

        return results

    # ------------------------------------------------------------------
    # Lemma / theorem declarations
    # ------------------------------------------------------------------

    def _extract_lemmas(self, content):
        results = []
        seen = set()

        for kind in ['lemma', 'theorem']:
            # Named lemma: lemma name: or lemma name[attr]: or lemma name :
            # NOT: lemma [simp]: (unnamed) or lemma "..." (direct statement)
            for m in re.finditer(
                rf'\b{kind}\b\s+([a-zA-Z_][\w\']*)',
                content
            ):
                name = m.group(1)
                if name in self._KEYWORDS or name in seen:
                    continue
                seen.add(name)
                results.append({'name': name, 'kind': kind})

        return results

    # ------------------------------------------------------------------
    # Locale declarations
    # ------------------------------------------------------------------

    def _extract_locales(self, content):
        results = []
        for m in re.finditer(r'\blocale\b\s+(\w+)', content):
            name = m.group(1)
            if name not in self._KEYWORDS:
                results.append(name)
        return results
