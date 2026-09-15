#!/usr/bin/env python3
"""
WAI-ARIA Virtual Screen Reader Implementation.

Builds an accessibility tree from HTML per WAI-ARIA 1.2, HTML-AAM 1.0,
and simplified ACCNAME 1.2, then supports linear and command-based navigation.

Uses only the Python standard library (html.parser).

"""

from html.parser import HTMLParser

# --- Constants ---

HEADING_LEVELS = {'h1': '1', 'h2': '2', 'h3': '3', 'h4': '4', 'h5': '5', 'h6': '6'}

CHILDREN_PRESENTATIONAL_ROLES = frozenset({
    'button', 'checkbox', 'heading', 'img', 'math',
    'menuitem', 'menuitemcheckbox', 'menuitemradio',
    'meter', 'option', 'progressbar', 'radio', 'scrollbar',
    'separator', 'slider', 'switch', 'tab', 'treeitem',
})

PRESENTATION_ROLES = frozenset({'presentation', 'none'})

DIALOG_ROLES = frozenset({'dialog', 'alertdialog'})

LANDMARK_ROLES = frozenset({
    'banner', 'complementary', 'contentinfo', 'figure',
    'form', 'main', 'navigation', 'region', 'search',
})

NAME_FROM_CONTENT_ROLES = frozenset({
    'heading', 'link', 'button', 'tab', 'menuitem',
    'menuitemcheckbox', 'menuitemradio', 'treeitem', 'option',
    'cell', 'columnheader', 'rowheader', 'tooltip', 'gridcell',
    'switch', 'checkbox', 'radio',
})

FOCUSABLE_TAG_NAMES = frozenset({'button', 'input', 'select', 'textarea'})

VOID_ELEMENTS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
})


# --- Simple DOM Node ---

class DomNode:
    __slots__ = ('tag', 'attrs', 'children', 'parent', 'text')

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs) if attrs else {}
        self.children = []
        self.parent = parent
        self.text = None

    def get(self, attr, default=''):
        return self.attrs.get(attr, default)

    def has_attr(self, attr):
        return attr in self.attrs

    def find_by_id(self, target_id):
        if self.text is None and self.get('id') == target_id:
            return self
        for child in self.children:
            if child.text is not None:
                continue
            result = child.find_by_id(target_id)
            if result:
                return result
        return None

    def find_all_with_attr(self, attr):
        results = []
        if self.text is None and self.has_attr(attr):
            results.append(self)
        for child in self.children:
            if child.text is not None:
                continue
            results.extend(child.find_all_with_attr(attr))
        return results

    @staticmethod
    def make_text(text, parent=None):
        node = DomNode('#text', parent=parent)
        node.text = text
        return node


# --- HTML Parser ---

class SimpleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = DomNode('#root')
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = DomNode(tag, attrs, parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_ELEMENTS:
            self._stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        if data:
            text_node = DomNode.make_text(data, parent=self._stack[-1])
            self._stack[-1].children.append(text_node)

    def handle_comment(self, data):
        pass


def parse_html(html):
    parser = SimpleHTMLParser()
    parser.feed(html)
    return parser.root


# --- Accessibility Node ---

class AccNode:
    __slots__ = ('role', 'spoken_role', 'name', 'children', 'heading_level', 'attr_labels')

    def __init__(self, role, spoken_role, name, children, heading_level=None, attr_labels=None):
        self.role = role
        self.spoken_role = spoken_role
        self.name = name
        self.children = children
        self.heading_level = heading_level
        self.attr_labels = attr_labels or []

    def spoken_phrase(self):
        parts = []
        if self.spoken_role:
            parts.append(self.spoken_role)
        if self.name:
            parts.append(self.name)
        parts.extend(self.attr_labels)
        return ', '.join(parts)

    def end_spoken_phrase(self):
        sp = self.spoken_phrase()
        return f'end of {sp}' if sp else ''


# --- Flat tree node ---

class FlatNode:
    __slots__ = ('acc', 'is_end')

    def __init__(self, acc, is_end=False):
        self.acc = acc
        self.is_end = is_end

    def spoken_phrase(self):
        return self.acc.end_spoken_phrase() if self.is_end else self.acc.spoken_phrase()


# --- Helper functions ---

def _is_text(node):
    return node.text is not None


def _is_el(node):
    return node.text is None and node.tag not in ('#root', '#text')


def _is_hidden(node):
    if _is_text(node):
        return not node.text.strip()
    if _is_el(node):
        if node.get('aria-hidden') == 'true':
            return True
        if node.has_attr('hidden'):
            return True
    return False


def _is_focusable(node):
    if not _is_el(node):
        return False
    if node.has_attr('tabindex'):
        return True
    if node.tag in FOCUSABLE_TAG_NAMES:
        return True
    if node.tag == 'a' and node.has_attr('href'):
        return True
    return False


def _implicit_role(node, container):
    tag = node.tag.lower()

    if tag in HEADING_LEVELS:
        return 'heading'

    simple_map = {
        'nav': 'navigation', 'main': 'main', 'article': 'article',
        'aside': 'complementary', 'ul': 'list', 'ol': 'list',
        'li': 'listitem', 'p': 'paragraph', 'button': 'button',
        'img': 'img', 'table': 'table', 'textarea': 'textbox',
        'hr': 'separator', 'fieldset': 'group', 'output': 'status',
        'menu': 'list', 'dialog': 'dialog',
    }
    if tag in simple_map:
        return simple_map[tag]

    if tag == 'a':
        return 'link' if node.has_attr('href') else 'generic'

    if tag == 'footer':
        p = node.parent
        while p and _is_el(p):
            if p.tag in ('article', 'aside', 'main', 'nav', 'section'):
                return 'generic'
            p = p.parent
        return 'contentinfo'

    if tag == 'header':
        p = node.parent
        while p and _is_el(p):
            if p.tag in ('article', 'aside', 'main', 'nav', 'section'):
                return 'generic'
            p = p.parent
        return 'banner'

    if tag == 'section':
        if node.get('aria-label') or node.get('aria-labelledby'):
            return 'region'
        return 'generic'

    if tag == 'form':
        if node.get('aria-label') or node.get('aria-labelledby'):
            return 'form'
        return 'generic'

    if tag == 'input':
        t = (node.get('type') or 'text').lower()
        m = {
            'text': 'textbox', 'password': 'textbox', 'email': 'textbox',
            'tel': 'textbox', 'url': 'textbox', 'search': 'searchbox',
            'number': 'spinbutton', 'range': 'slider', 'checkbox': 'checkbox',
            'radio': 'radio', 'button': 'button', 'submit': 'button',
            'reset': 'button', 'image': 'button', 'hidden': 'generic',
        }
        return m.get(t, 'textbox')

    if tag == 'select':
        if node.has_attr('multiple'):
            return 'listbox'
        size = node.get('size', '1')
        try:
            if int(size) > 1:
                return 'listbox'
        except (ValueError, TypeError):
            pass
        return 'combobox'

    return 'generic'


def _get_text_content(node):
    if _is_text(node):
        return node.text.strip()
    if _is_el(node) or node.tag == '#root':
        if _is_el(node) and node.get('aria-hidden') == 'true':
            return ''
        parts = []
        for child in node.children:
            if _is_text(child):
                t = child.text.strip()
                if t:
                    parts.append(t)
            elif _is_el(child):
                if child.get('aria-hidden') == 'true':
                    continue
                t = _get_text_content(child)
                if t:
                    parts.append(t)
        return ' '.join(parts)
    return ''


def _accessible_name(node, container):
    if _is_text(node):
        return node.text.strip()
    if not _is_el(node):
        return ''

    # aria-labelledby
    lby = node.get('aria-labelledby', '').strip()
    if lby:
        names = []
        for ref_id in lby.split():
            ref = container.find_by_id(ref_id)
            if ref:
                names.append(_get_text_content(ref))
        if names:
            return ' '.join(n for n in names if n)

    # aria-label
    lab = node.get('aria-label', '').strip()
    if lab:
        return lab

    # label[for]
    if node.tag in ('input', 'textarea', 'select') and node.get('id'):
        for el in container.find_all_with_attr('for'):
            if el.tag == 'label' and el.get('for') == node.get('id'):
                return _get_text_content(el)

    # alt for images
    if node.tag == 'img' and node.has_attr('alt'):
        return node.get('alt', '')

    # title fallback
    if node.has_attr('title'):
        return node.get('title', '')

    # Name from content
    explicit = node.get('role', '').strip().split()
    role = explicit[0] if explicit else _implicit_role(node, container)
    if role in NAME_FROM_CONTENT_ROLES:
        return _get_text_content(node)

    return ''


def _attr_labels(node, role):
    labels = []
    if not _is_el(node):
        return labels
    if role == 'heading':
        lv = node.get('aria-level')
        if not lv and node.tag in HEADING_LEVELS:
            lv = HEADING_LEVELS[node.tag]
        if lv:
            labels.append(f'level {lv}')
    if role in DIALOG_ROLES:
        m = node.get('aria-modal')
        if m == 'true':
            labels.append('modal')
        elif m == 'false':
            labels.append('not modal')
    return labels


# --- Tree building ---

def _collect_owned_ids(root):
    ids = set()
    for el in root.find_all_with_attr('aria-owns'):
        for ref_id in el.get('aria-owns', '').split():
            ids.add(ref_id)
    return ids


def _build(node, container, owned_ids, inherit_inert, inherit_presentational, parent_dialog):
    if _is_hidden(node):
        return []

    # Text nodes
    if _is_text(node):
        text = node.text.strip()
        if not text:
            return []
        if inherit_inert:
            return []
        if inherit_presentational:
            return []
        return [AccNode(role='generic', spoken_role='', name=text, children=[])]

    if not _is_el(node) and node.tag != '#root':
        return []

    # Determine role
    explicit_parts = node.get('role', '').strip().split()
    explicit_role = explicit_parts[0] if explicit_parts else ''

    is_explicit_pres = explicit_role in PRESENTATION_ROLES
    is_inherited_pres = (inherit_presentational and not explicit_role and not _is_focusable(node))
    is_presentational = is_explicit_pres or is_inherited_pres

    if is_presentational:
        role = 'presentation'
        spoken_role = ''
    else:
        role = explicit_role if (explicit_role and explicit_role not in PRESENTATION_ROLES) else _implicit_role(node, container)
        rdesc = node.get('aria-roledescription', '').strip()
        if rdesc:
            spoken_role = rdesc
        elif role == 'generic':
            spoken_role = ''
        else:
            spoken_role = role

    # Check inert
    is_explicit_inert = node.has_attr('inert')
    is_modal = (role in DIALOG_ROLES and node.get('aria-modal') == 'true') or \
               (node.tag == 'dialog' and node.has_attr('open'))

    node_is_inert = is_explicit_inert or (inherit_inert and not is_modal)

    if node_is_inert:
        result = []
        for child in node.children:
            if _is_el(child) and child.get('id') in owned_ids:
                continue
            result.extend(_build(child, container, owned_ids,
                                 inherit_inert=True,
                                 inherit_presentational=False,
                                 parent_dialog=parent_dialog))
        return result

    # Compute properties
    name = _accessible_name(node, container)
    al = _attr_labels(node, role)
    hl = None
    if role == 'heading':
        hl = node.get('aria-level')
        if not hl and node.tag in HEADING_LEVELS:
            hl = HEADING_LEVELS[node.tag]

    new_parent_dialog = node if role in DIALOG_ROLES else parent_dialog

    children_pres = (role in CHILDREN_PRESENTATIONAL_ROLES) or \
                    (inherit_presentational and _is_el(node))

    # Presentational node: promote children
    if is_presentational:
        result = []
        for child in node.children:
            if _is_el(child) and child.get('id') in owned_ids:
                continue
            result.extend(_build(child, container, owned_ids,
                                 inherit_inert=False,
                                 inherit_presentational=children_pres,
                                 parent_dialog=new_parent_dialog))
        return result

    # Normal node: build children
    children = []
    for child in node.children:
        if _is_el(child) and child.get('id') in owned_ids:
            continue
        children.extend(_build(child, container, owned_ids,
                               inherit_inert=False,
                               inherit_presentational=children_pres,
                               parent_dialog=new_parent_dialog))

    # aria-owns
    owns = node.get('aria-owns', '').strip()
    if owns:
        for ref_id in owns.split():
            owned_el = container.find_by_id(ref_id)
            if owned_el and not _is_hidden(owned_el):
                children.extend(_build(owned_el, container, owned_ids,
                                       inherit_inert=False,
                                       inherit_presentational=children_pres,
                                       parent_dialog=new_parent_dialog))

    return [AccNode(role=role, spoken_role=spoken_role, name=name,
                    children=children, heading_level=hl, attr_labels=al)]


def _flatten(acc_node):
    sp = acc_node.spoken_phrase()
    has_children = bool(acc_node.children)

    if sp:
        result = [FlatNode(acc_node)]
        if has_children:
            for child in acc_node.children:
                result.extend(_flatten(child))
            result.append(FlatNode(acc_node, is_end=True))
        return result
    else:
        result = []
        for child in acc_node.children:
            result.extend(_flatten(child))
        return result


# --- VirtualScreenReader ---

class VirtualScreenReader:
    def __init__(self):
        self._flat = []
        self._idx = 0
        self._log = []

    def start(self, html):
        root = parse_html(html)

        # Use body if present, else root
        body = None
        for child in root.children:
            if _is_el(child) and child.tag == 'body':
                body = child
                break
        if body is None:
            body = root

        owned_ids = _collect_owned_ids(body)

        nodes = _build(body, body, owned_ids,
                       inherit_inert=False,
                       inherit_presentational=False,
                       parent_dialog=None)

        if not nodes:
            doc = AccNode(role='document', spoken_role='document', name='', children=[])
            self._flat = _flatten(doc)
        elif len(nodes) == 1 and nodes[0].role == 'document':
            self._flat = _flatten(nodes[0])
        else:
            doc = AccNode(role='document', spoken_role='document', name='', children=nodes)
            self._flat = _flatten(doc)

        self._idx = 0
        self._log = []
        if self._flat:
            self._log.append(self._flat[0].spoken_phrase())

    def next(self):
        if not self._flat:
            return ''
        self._idx = (self._idx + 1) % len(self._flat)
        sp = self._flat[self._idx].spoken_phrase()
        self._log.append(sp)
        return sp

    def previous(self):
        if not self._flat:
            return ''
        self._idx = (self._idx - 1) % len(self._flat)
        sp = self._flat[self._idx].spoken_phrase()
        self._log.append(sp)
        return sp

    def last_spoken_phrase(self):
        return self._log[-1] if self._log else ''

    def spoken_phrase_log(self):
        return list(self._log)

    def clear_spoken_phrase_log(self):
        self._log = []

    def perform(self, command):
        if command == 'moveToNextHeading':
            return self._find_next(lambda n: not n.is_end and n.acc.role == 'heading')
        if command == 'moveToPreviousHeading':
            return self._find_prev(lambda n: not n.is_end and n.acc.role == 'heading')
        if command == 'moveToNextLandmark':
            return self._find_next(lambda n: not n.is_end and n.acc.role in LANDMARK_ROLES)
        if command == 'moveToPreviousLandmark':
            return self._find_prev(lambda n: not n.is_end and n.acc.role in LANDMARK_ROLES)

        if command.startswith('moveToNextHeadingLevel'):
            lv = command[-1]
            return self._find_next(lambda n, l=lv: not n.is_end and n.acc.role == 'heading' and n.acc.heading_level == l)
        if command.startswith('moveToPreviousHeadingLevel'):
            lv = command[-1]
            return self._find_prev(lambda n, l=lv: not n.is_end and n.acc.role == 'heading' and n.acc.heading_level == l)

        return None

    def _find_next(self, predicate):
        if not self._flat:
            return None
        n = len(self._flat)
        for i in range(1, n + 1):
            idx = (self._idx + i) % n
            if predicate(self._flat[idx]):
                self._idx = idx
                sp = self._flat[idx].spoken_phrase()
                self._log.append(sp)
                return sp
        return None

    def _find_prev(self, predicate):
        if not self._flat:
            return None
        n = len(self._flat)
        for i in range(1, n + 1):
            idx = (self._idx - i) % n
            if predicate(self._flat[idx]):
                self._idx = idx
                sp = self._flat[idx].spoken_phrase()
                self._log.append(sp)
                return sp
        return None
