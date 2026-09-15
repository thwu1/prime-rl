from storage.journal import Journal
from storage.filesystem import FileSystem


def test_log_operation():
    fs = FileSystem()
    j = Journal(fs)
    eid = j.log_operation("write", "test.txt", b"data")
    assert eid == 0
    assert len(j.entries) == 1


def test_commit():
    fs = FileSystem()
    j = Journal(fs)
    eid = j.log_operation("write", "test.txt", b"data")
    j.commit(eid)
    assert j.entries[eid]["committed"]
    assert len(j.get_uncommitted()) == 0
