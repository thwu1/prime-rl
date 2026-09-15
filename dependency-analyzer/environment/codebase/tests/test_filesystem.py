from storage.filesystem import FileSystem


def test_create_file():
    fs = FileSystem(num_blocks=16)
    assert fs.create_file("test.txt")
    assert not fs.create_file("test.txt")


def test_write_file():
    fs = FileSystem(num_blocks=16)
    fs.create_file("test.txt")
    fs.write_file("test.txt", b"hello world")
    assert len(fs.file_table["test.txt"]) == 1
