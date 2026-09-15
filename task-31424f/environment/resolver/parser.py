"""Puppetfile parser for Puppet module dependency manifests."""

import re


class PuppetfileEntry:
    """Represents a single module entry from a Puppetfile."""

    def __init__(self, name, constraint=None, source='forge', git_url=None, git_ref=None):
        self.name = name
        self.constraint = constraint
        self.source = source
        self.git_url = git_url
        self.git_ref = git_ref

    def __repr__(self):
        if self.source == 'git':
            return f"PuppetfileEntry({self.name}, git={self.git_url}, ref={self.git_ref})"
        return f"PuppetfileEntry({self.name}, {self.constraint})"


def parse_puppetfile(path):
    """Parse a Puppetfile and return a list of PuppetfileEntry objects.

    Handles:
    - mod 'owner/name', 'version_constraint'  (forge with constraint)
    - mod 'owner/name'                        (forge, latest)
    - mod 'owner/name', :git => 'url', :tag => 'ref'  (git source)
    - Comments starting with #
    - The forge directive (informational, ignored)
    """
    with open(path) as f:
        content = f.read()

    # Strip comments (everything after # on each line)
    lines = []
    for line in content.split('\n'):
        stripped = line.split('#')[0].rstrip()
        lines.append(stripped)
    text = '\n'.join(lines)

    entries = []

    # Match mod declarations: mod 'name'[, rest]
    # rest ends at the next mod line, a blank line, or end of string
    mod_pattern = re.compile(
        r"mod\s+'([^']+)'(?:\s*,\s*(.*?))?(?=\nmod\s|\n\s*\n|\Z)",
        re.DOTALL
    )

    for match in mod_pattern.finditer(text):
        name = match.group(1)
        rest = match.group(2)

        if rest is None:
            # No constraint or source — resolve latest from forge
            entries.append(PuppetfileEntry(name))
        elif ':git' in rest:
            # Git-sourced module
            git_match = re.search(r":git\s*=>\s*'([^']+)'", rest)
            ref_match = re.search(r":(?:tag|ref|branch)\s*=>\s*'([^']+)'", rest)
            entries.append(PuppetfileEntry(
                name,
                source='git',
                git_url=git_match.group(1) if git_match else None,
                git_ref=ref_match.group(1) if ref_match else None,
            ))
        else:
            # Version constraint from forge
            constraint = rest.strip().strip("'\"")
            entries.append(PuppetfileEntry(name, constraint=constraint))

    return entries
