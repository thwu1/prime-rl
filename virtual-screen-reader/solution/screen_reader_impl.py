
"""
W3C-compliant Virtual Screen Reader.
WAI-ARIA 1.2 · HTML-AAM 1.0 · ACCNAME 1.2
Advanced: aria-owns restructuring, presentational children,
accessible value, embedded controls in ACCNAME, aria-flowto.
"""

from bs4 import BeautifulSoup, NavigableString, Tag
from dataclasses import dataclass
from typing import Optional, List


# ── Implicit Role Mappings (HTML-AAM 1.0) ──

def _input_role(el):
    t = (el.get("type") or "text").lower()
    return {
        "button": "button", "checkbox": "checkbox", "email": "textbox",
        "image": "button", "number": "spinbutton", "radio": "radio",
        "range": "slider", "reset": "button", "search": "searchbox",
        "submit": "button", "tel": "textbox", "text": "textbox",
        "url": "textbox",
    }.get(t, "textbox")


def get_implicit_role(el):
    """Get the implicit HTML-AAM role (ignoring explicit role attribute)."""
    if not isinstance(el, Tag):
        return ""
    tag = el.name.lower()
    simple = {
        "article": "article", "aside": "complementary", "body": "document",
        "button": "button", "datalist": "listbox", "details": "group",
        "dialog": "dialog", "fieldset": "group", "figure": "figure",
        "h1": "heading", "h2": "heading", "h3": "heading",
        "h4": "heading", "h5": "heading", "h6": "heading",
        "hr": "separator", "li": "listitem", "main": "main",
        "math": "math", "menu": "list", "meter": "meter",
        "nav": "navigation", "ol": "list", "optgroup": "group",
        "option": "option", "output": "status", "progress": "progressbar",
        "summary": "button", "table": "table", "tbody": "rowgroup",
        "td": "cell", "textarea": "textbox", "tfoot": "rowgroup",
        "th": "columnheader", "thead": "rowgroup", "tr": "row", "ul": "list",
    }
    if tag in simple:
        return simple[tag]
    if tag == "a":
        return "link" if el.has_attr("href") else "generic"
    if tag == "header":
        return "banner"
    if tag == "footer":
        return "contentinfo"
    if tag == "form":
        return "form" if (el.get("aria-label") or el.get("aria-labelledby")) else "generic"
    if tag == "section":
        return "region" if (el.get("aria-label") or el.get("aria-labelledby")) else "generic"
    if tag == "img":
        alt = el.get("alt")
        if alt is None:
            return "img"
        return "img" if alt != "" else "presentation"
    if tag == "input":
        return _input_role(el)
    if tag == "select":
        if el.get("multiple"):
            return "listbox"
        try:
            if el.get("size") and int(el.get("size")) > 1:
                return "listbox"
        except (ValueError, TypeError):
            pass
        return "combobox"
    return "generic"


def get_role(el):
    """Get ARIA role: explicit role attribute takes priority, else implicit."""
    if not isinstance(el, Tag):
        return ""
    explicit = el.get("role", "").strip().split()
    if explicit and explicit[0]:
        return explicit[0]
    return get_implicit_role(el)


def has_explicit_role(el):
    """Check if element has an explicit role attribute."""
    if not isinstance(el, Tag):
        return False
    return bool(el.get("role", "").strip())


# ── Constants ──

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

NAME_FROM_CONTENT = {
    "button", "cell", "checkbox", "columnheader", "gridcell", "heading",
    "link", "menuitem", "menuitemcheckbox", "menuitemradio", "option",
    "radio", "row", "rowheader", "switch", "tab", "tooltip", "treeitem",
}

GENERIC_ROLES = {"generic", "presentation", "none", ""}

LANDMARK_ROLES = {
    "banner", "complementary", "contentinfo", "form",
    "main", "navigation", "region", "search",
}

VALUE_ROLES = {"slider", "spinbutton", "progressbar", "scrollbar", "meter"}

EMBEDDED_CONTROL_ROLES = {
    "textbox", "searchbox", "slider", "spinbutton", "combobox", "listbox",
}

# WAI-ARIA required owned elements per parent role
REQUIRED_OWNED = {
    "table": {"row", "rowgroup"},
    "rowgroup": {"row"},
    "row": {"cell", "gridcell", "columnheader", "rowheader"},
    "list": {"listitem"},
    "tablist": {"tab"},
    "tree": {"treeitem"},
    "menu": {"menuitem", "menuitemcheckbox", "menuitemradio"},
    "grid": {"row", "rowgroup"},
}


# ── Utility ──

def is_hidden(el):
    if not isinstance(el, Tag):
        return False
    return el.has_attr("hidden") or el.get("aria-hidden", "").lower() == "true"


def text_content(el):
    if isinstance(el, NavigableString):
        return str(el).strip()
    if isinstance(el, Tag):
        if is_hidden(el):
            return ""
        return " ".join(filter(None, (text_content(c) for c in el.children)))
    return ""


def get_accessible_value(el):
    """Get accessible value for widget roles."""
    role = get_role(el)
    if role not in VALUE_ROLES:
        return ""
    vt = el.get("aria-valuetext", "").strip()
    if vt:
        return vt
    vn = el.get("aria-valuenow", "").strip()
    return vn


def text_content_with_embedded_controls(el):
    """ACCNAME 2B: embedded controls contribute their value, not text."""
    if isinstance(el, NavigableString):
        return str(el).strip()
    if isinstance(el, Tag):
        if is_hidden(el):
            return ""
        role = get_role(el)
        if role in EMBEDDED_CONTROL_ROLES:
            if role in VALUE_ROLES:
                v = get_accessible_value(el)
                if v:
                    return v
            if role in ("textbox", "searchbox"):
                v = el.get("value", "").strip()
                return v if v else text_content(el)
            return ""
        return " ".join(filter(None,
            (text_content_with_embedded_controls(c) for c in el.children)))
    return ""


def compute_name(el, soup):
    """Compute accessible name following ACCNAME 1.2 priority."""
    lb = el.get("aria-labelledby", "").strip()
    if lb:
        parts = []
        for ref_id in lb.split():
            ref_el = soup.find(id=ref_id)
            if ref_el:
                parts.append(text_content_with_embedded_controls(ref_el))
        name = " ".join(filter(None, parts))
        if name:
            return name
    al = el.get("aria-label", "").strip()
    if al:
        return al
    if el.name.lower() == "img":
        return el.get("alt", "")
    if get_role(el) in NAME_FROM_CONTENT:
        return text_content(el)
    return ""


def compute_description(el, soup):
    db = el.get("aria-describedby", "").strip()
    if db:
        parts = []
        for ref_id in db.split():
            ref_el = soup.find(id=ref_id)
            if ref_el:
                parts.append(text_content(ref_el))
        return " ".join(parts)
    return ""


# ── Node ──

@dataclass
class Node:
    role: str
    name: str
    value: str
    description: str
    level: Optional[int]
    is_end: bool
    element: object = None

    @property
    def spoken_phrase(self) -> str:
        parts = []
        if self.is_end:
            parts.append(f"end of {self.role}")
            if self.name:
                parts.append(self.name)
        else:
            if self.role and self.role not in GENERIC_ROLES:
                parts.append(self.role)
            if self.name:
                parts.append(self.name)
            if self.value and self.value != self.name:
                parts.append(self.value)
            if self.description and self.description != self.name:
                parts.append(self.description)
            if self.level is not None:
                parts.append(f"level {self.level}")
        return ", ".join(parts)


# ── Virtual Screen Reader ──

class VirtualScreenReader:
    def __init__(self):
        self._nodes: List[Node] = []
        self._index: int = 0
        self._log: List[str] = []
        self._soup = None

    # ── Startup ──

    def start(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body") or soup
        self._nodes = []
        self._soup = soup

        modal = self._find_modal(body)
        root = modal if modal else body

        reparented = self._resolve_ownership(root, soup)
        visited = set()
        self._process(root, soup, False, reparented, visited, None)

        self._index = 0
        self._log = []
        if self._nodes:
            p = self._nodes[0].spoken_phrase
            self._log.append(p)
            return p
        return ""

    def _find_modal(self, el):
        if not isinstance(el, Tag):
            return None
        if is_hidden(el):
            return None
        if (el.get("aria-modal", "").lower() == "true"
                and get_role(el) in ("dialog", "alertdialog")):
            return el
        for child in el.children:
            r = self._find_modal(child)
            if r:
                return r
        return None

    # ── aria-owns resolution ──

    def _resolve_ownership(self, root, soup):
        """Pre-pass: determine which element IDs are reparented via aria-owns.
        First owner in DOM order wins. Cycles are detected and broken."""
        refs = []

        def collect(el):
            if not isinstance(el, Tag) or is_hidden(el):
                return
            owns = el.get("aria-owns", "").strip()
            if owns:
                for ref_id in owns.split():
                    ref_el = soup.find(id=ref_id)
                    if ref_el and isinstance(ref_el, Tag):
                        refs.append((el, ref_id))
            for child in el.children:
                if isinstance(child, Tag):
                    collect(child)

        collect(root)

        reparented = set()
        owners = {}

        for owner_el, ref_id in refs:
            if ref_id in reparented:
                continue
            if self._would_cycle(owner_el, ref_id, owners):
                continue
            reparented.add(ref_id)
            owners[ref_id] = owner_el

        return reparented

    def _would_cycle(self, owner_el, new_id, owners):
        """Check if making owner_el own new_id creates a cycle in the
        ownership graph."""
        current = owner_el
        seen = set()
        while isinstance(current, Tag):
            cid = current.get("id", "")
            if cid == new_id:
                return True
            if cid in seen:
                return True
            seen.add(cid)
            if cid and cid in owners:
                current = owners[cid]
            else:
                break
        return False

    # ── Tree construction ──

    def _process(self, el, soup, inert, reparented, visited, inherit_pres):
        # Text nodes
        if isinstance(el, NavigableString):
            t = str(el).strip()
            if t:
                self._nodes.append(Node("", t, "", "", None, False, None))
            return
        if not isinstance(el, Tag):
            return
        if is_hidden(el):
            return

        # Inert handling
        el_inert = inert or el.has_attr("inert")
        if el_inert:
            is_modal = (el.get("aria-modal", "").lower() == "true"
                        and get_role(el) in ("dialog", "alertdialog"))
            if is_modal:
                el_inert = False
            else:
                return

        # Cycle / duplicate prevention
        py_id = id(el)
        if py_id in visited:
            return
        visited.add(py_id)

        role = get_role(el)

        # Presentational children inheritance (WAI-ARIA required owned)
        if inherit_pres is not None and not has_explicit_role(el):
            implicit = get_implicit_role(el)
            required = REQUIRED_OWNED.get(inherit_pres, set())
            if implicit in required:
                role = "presentation"

        # Generic / transparent: promote children
        if role in GENERIC_ROLES:
            implicit = get_implicit_role(el)
            if role in ("presentation", "none") and implicit in REQUIRED_OWNED:
                new_inherit = implicit
            elif role in ("presentation", "none"):
                new_inherit = None
            else:
                new_inherit = inherit_pres
            for child in el.children:
                if isinstance(child, Tag) and child.get("id", "") in reparented:
                    continue
                self._process(child, soup, el_inert, reparented, visited,
                              new_inherit)
            self._process_owned(el, soup, el_inert, reparented, visited,
                                new_inherit)
            return

        # Non-generic element
        name = compute_name(el, soup)
        desc = compute_description(el, soup)
        if desc == name:
            desc = ""
        value = get_accessible_value(el)

        level = None
        if role == "heading":
            level = HEADING_LEVELS.get(el.name.lower())
            al = el.get("aria-level")
            if al:
                try:
                    level = int(al)
                except (ValueError, TypeError):
                    pass

        start_idx = len(self._nodes)

        if role not in NAME_FROM_CONTENT:
            for child in el.children:
                if isinstance(child, Tag) and child.get("id", "") in reparented:
                    continue
                self._process(child, soup, el_inert, reparented, visited, None)
            self._process_owned(el, soup, el_inert, reparented, visited, None)
        else:
            self._process_naming_children(el, soup, el_inert, reparented,
                                          visited)

        end_idx = len(self._nodes)
        has_children = end_idx > start_idx

        enter_node = Node(role, name, value, desc, level, False, el)
        self._nodes.insert(start_idx, enter_node)

        if has_children:
            self._nodes.append(Node(role, name, "", "", None, True, None))

    def _process_owned(self, el, soup, inert, reparented, visited,
                       inherit_pres):
        owns = el.get("aria-owns", "").strip()
        if not owns:
            return
        for ref_id in owns.split():
            ref_el = soup.find(id=ref_id)
            if ref_el and isinstance(ref_el, Tag):
                self._process(ref_el, soup, inert, reparented, visited,
                              inherit_pres)

    def _process_naming_children(self, el, soup, inert, reparented, visited):
        """Process children of name-from-content elements. Text descendants
        are absorbed into the parent name; only non-generic child elements
        with their own roles appear as separate tree entries."""
        for child in el.children:
            if isinstance(child, Tag):
                if child.get("id", "") in reparented:
                    continue
                if is_hidden(child):
                    continue
                child_role = get_role(child)
                if child_role not in GENERIC_ROLES:
                    self._process(child, soup, inert, reparented, visited,
                                  None)
                else:
                    self._process_naming_children(child, soup, inert,
                                                  reparented, visited)

    # ── Navigation ──

    def next(self) -> str:
        if not self._nodes:
            return ""
        self._index = (self._index + 1) % len(self._nodes)
        p = self._nodes[self._index].spoken_phrase
        self._log.append(p)
        return p

    def previous(self) -> str:
        if not self._nodes:
            return ""
        self._index = (self._index - 1) % len(self._nodes)
        p = self._nodes[self._index].spoken_phrase
        self._log.append(p)
        return p

    def move_to_next(self, role: str) -> str:
        if not self._nodes:
            return ""
        n = len(self._nodes)
        for i in range(1, n + 1):
            idx = (self._index + i) % n
            nd = self._nodes[idx]
            if not nd.is_end and nd.role == role:
                self._index = idx
                p = nd.spoken_phrase
                self._log.append(p)
                return p
        return ""

    def move_to_previous(self, role: str) -> str:
        if not self._nodes:
            return ""
        n = len(self._nodes)
        for i in range(1, n + 1):
            idx = (self._index - i) % n
            nd = self._nodes[idx]
            if not nd.is_end and nd.role == role:
                self._index = idx
                p = nd.spoken_phrase
                self._log.append(p)
                return p
        return ""

    def move_to_next_landmark(self) -> str:
        if not self._nodes:
            return ""
        n = len(self._nodes)
        for i in range(1, n + 1):
            idx = (self._index + i) % n
            nd = self._nodes[idx]
            if not nd.is_end and nd.role in LANDMARK_ROLES:
                self._index = idx
                p = nd.spoken_phrase
                self._log.append(p)
                return p
        return ""

    def move_to_flowto(self) -> str:
        """Follow aria-flowto of the current node's element."""
        if not self._nodes:
            return ""
        cur = self._nodes[self._index]
        if cur.element is None:
            return ""
        flowto = cur.element.get("aria-flowto", "").strip()
        if not flowto:
            return ""
        target_id = flowto.split()[0]
        for i, nd in enumerate(self._nodes):
            if (nd.element is not None
                    and nd.element.get("id") == target_id
                    and not nd.is_end):
                self._index = i
                p = nd.spoken_phrase
                self._log.append(p)
                return p
        return ""

    def current(self) -> str:
        if not self._nodes:
            return ""
        return self._nodes[self._index].spoken_phrase

    def spoken_phrase_log(self) -> list:
        return list(self._log)
