from app.storage import LocalDocumentStorage


def test_save_and_read_roundtrip(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    key = storage.save(project_id=1, filename="report.pdf", content=b"hello")

    assert storage.read(key) == b"hello"
    assert key.startswith("1/")
    assert key.endswith(".pdf")


def test_overwrite_replaces_content(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    key = storage.save(project_id=1, filename="report.pdf", content=b"v1")

    storage.overwrite(key, b"v2")

    assert storage.read(key) == b"v2"


def test_delete_removes_file(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    key = storage.save(project_id=1, filename="report.pdf", content=b"hello")

    storage.delete(key)

    assert not (tmp_path / key).exists()


def test_delete_project_dir_removes_all_documents(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    storage.save(project_id=1, filename="a.pdf", content=b"a")
    storage.save(project_id=1, filename="b.docx", content=b"b")

    storage.delete_project_dir(1)

    assert not (tmp_path / "1").exists()
