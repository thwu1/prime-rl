
"""
Minimal Git object library — reads loose Git objects.

Supports blobs, trees, commits, and tags via the standard loose object
format (zlib-compressed files under .git/objects/XX/YYYY...).
"""

import os
import hashlib
import zlib
import collections


class GitRepository:
    """Represents a Git repository on disk."""

    def __init__(self, path):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")
        if not os.path.isdir(self.gitdir):
            raise Exception(f"Not a Git repository: {path}")


class GitObject:
    """Base class for all Git object types."""

    def __init__(self, data=None):
        if data is not None:
            self.deserialize(data)
        else:
            self.init()

    def serialize(self):
        raise NotImplementedError

    def deserialize(self, data):
        raise NotImplementedError

    def init(self):
        pass


class GitBlob(GitObject):
    fmt = b'blob'

    def serialize(self):
        return self.blobdata

    def deserialize(self, data):
        self.blobdata = data

    def init(self):
        self.blobdata = b''


class GitCommit(GitObject):
    fmt = b'commit'

    def serialize(self):
        return kvlm_serialize(self.kvlm)

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)

    def init(self):
        self.kvlm = collections.OrderedDict()


class GitTree(GitObject):
    fmt = b'tree'

    def serialize(self):
        return tree_serialize(self)

    def deserialize(self, data):
        self.items = tree_parse(data)

    def init(self):
        self.items = []


class GitTag(GitObject):
    fmt = b'tag'

    def serialize(self):
        return kvlm_serialize(self.kvlm)

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)

    def init(self):
        self.kvlm = collections.OrderedDict()


class GitTreeLeaf:
    """A single entry inside a tree object."""

    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha


# ---------------------------------------------------------------------------
# Key-Value List with Message (KVLM) — used by commits and tags
# ---------------------------------------------------------------------------

def kvlm_parse(raw, start=0, dct=None):
    """Parse commit/tag content into an OrderedDict.

    Keys are byte-string field names (b'tree', b'parent', ...).
    The commit message is stored under the key ``None``.
    """
    if not dct:
        dct = collections.OrderedDict()

    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    # Blank line → everything after it is the message body.
    if (spc < 0) or (nl < spc):
        assert nl == start
        dct[None] = raw[start + 1:]
        return dct

    key = raw[start:spc]

    # Find the end of the value: look for a newline NOT followed by a space.
    end = start
    while True:
        end = raw.find(b'\n', end + 1)
        if raw[end + 1:end + 2] != b' ':
            break

    value = raw[spc + 1:end].replace(b'\n ', b'\n')

    if key in dct:
        if type(dct[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [dct[key], value]
    else:
        dct[key] = value

    return kvlm_parse(raw, start=end + 1, dct=dct)


def kvlm_serialize(kvlm):
    """Serialize an OrderedDict back into raw commit/tag bytes."""
    ret = b''
    for k in kvlm.keys():
        if k is None:
            continue
        val = kvlm[k]
        if type(val) != list:
            val = [val]
        for v in val:
            ret += k + b' ' + v.replace(b'\n', b'\n ') + b'\n'
    ret += b'\n' + kvlm[None]
    return ret


# ---------------------------------------------------------------------------
# Tree object parsing / serialization
# ---------------------------------------------------------------------------

def tree_parse_one(raw, start=0):
    """Parse a single entry from tree object bytes."""
    x = raw.find(b' ', start)
    assert x - start == 5 or x - start == 6

    mode = raw[start:x]

    y = raw.find(b'\x00', x)
    path = raw[x + 1:y]

    raw_sha = int.from_bytes(raw[y + 1:y + 21], "big")
    sha = format(raw_sha, "040x")
    return y + 21, GitTreeLeaf(mode, path.decode("utf8"), sha)


def tree_parse(raw):
    """Parse all entries from tree object bytes."""
    pos = 0
    mx = len(raw)
    ret = []
    while pos < mx:
        pos, data = tree_parse_one(raw, pos)
        ret.append(data)
    return ret


def tree_serialize(obj):
    """Serialize a GitTree back to raw bytes."""
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' '
        ret += i.path.encode("utf8")
        ret += b'\x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")
    return ret


# ---------------------------------------------------------------------------
# Object read / hash
# ---------------------------------------------------------------------------

def object_read(repo, sha):
    """Read the object identified by *sha* from *repo*.

    Returns an instance of GitBlob, GitCommit, GitTree, or GitTag.
    """
    # --- Try loose object first ---
    path = os.path.join(repo.gitdir, "objects", sha[0:2], sha[2:])
    if os.path.isfile(path):
        with open(path, "rb") as f:
            raw = zlib.decompress(f.read())

        x = raw.find(b' ')
        fmt = raw[0:x]

        y = raw.find(b'\x00', x)
        size = int(raw[x + 1:y].decode("ascii"))
        if size != len(raw) - y - 1:
            raise Exception(f"Malformed object {sha}: bad length")

        match fmt:
            case b'commit': c = GitCommit
            case b'tree':   c = GitTree
            case b'tag':    c = GitTag
            case b'blob':   c = GitBlob
            case _:
                raise Exception(
                    f"Unknown type {fmt.decode('ascii')} for object {sha}")

        return c(raw[y + 1:])

    # Object not found in loose storage
    raise Exception(f"Object {sha} not found")


def object_hash(data, fmt):
    """Compute the SHA-1 hash of an object with the given type and data."""
    header = fmt + b' ' + str(len(data)).encode() + b'\x00'
    full_data = header + data
    return hashlib.sha1(full_data).hexdigest()
