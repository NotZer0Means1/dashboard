from app.config import get_settings
from app.storage import LocalDocumentStorage, S3DocumentStorage, get_storage


def test_save_and_read_roundtrip(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    key = storage.save(project_id=1, document_id=7, filename="report.pdf", content=b"hello")

    assert storage.read(key) == b"hello"
    assert key == "1/7/report.pdf"


def test_overwrite_replaces_content(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    key = storage.save(project_id=1, document_id=7, filename="report.pdf", content=b"v1")

    storage.overwrite(key, b"v2")

    assert storage.read(key) == b"v2"


def test_delete_removes_file(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    key = storage.save(project_id=1, document_id=7, filename="report.pdf", content=b"hello")

    storage.delete(key)

    assert not (tmp_path / key).exists()


def test_delete_project_dir_removes_all_documents(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    storage.save(project_id=1, document_id=7, filename="a.pdf", content=b"a")
    storage.save(project_id=1, document_id=8, filename="b.docx", content=b"b")

    storage.delete_project_dir(1)

    assert not (tmp_path / "1").exists()


def test_save_sanitizes_path_traversal_in_filename(tmp_path):
    storage = LocalDocumentStorage(base_dir=tmp_path)
    key = storage.save(
        project_id=1, document_id=7, filename="../../etc/passwd", content=b"malicious"
    )

    assert key == "1/7/passwd"
    assert (tmp_path / "1" / "7" / "passwd").exists()


def test_get_storage_defaults_to_local(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    get_settings.cache_clear()

    assert isinstance(get_storage(), LocalDocumentStorage)

    get_settings.cache_clear()


def test_get_storage_switches_to_s3_backend(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    get_settings.cache_clear()

    assert isinstance(get_storage(), S3DocumentStorage)

    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    get_settings.cache_clear()
