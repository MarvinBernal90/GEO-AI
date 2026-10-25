from pathlib import Path
from unittest.mock import Mock

import pytest

from evals import corpus


def test_build_corpus_reports_missing_pgm_pdfs_before_loading(tmp_path, monkeypatch):
    legal_dir = tmp_path / "legal"
    legal_dir.mkdir()
    missing_pdf = legal_dir / "Article 302.pdf"
    loader = Mock(side_effect=AssertionError("loader called"))

    monkeypatch.setattr(corpus, "LEGAL_DIR", legal_dir)
    monkeypatch.setattr(corpus, "PGM_FILES", ("Article 302.pdf",))
    monkeypatch.setattr(corpus, "load_corpus_from_directory", loader)

    with pytest.raises(FileNotFoundError, match=r"Required PGM PDF\(s\) not found") as exc_info:
        corpus.build_corpus(object(), Mock(), log=Mock())

    assert str(missing_pdf) in str(exc_info.value)
    loader.assert_not_called()


def test_build_corpus_copies_pgm_pdfs_into_staging_directory(tmp_path, monkeypatch):
    legal_dir = tmp_path / "legal"
    legal_dir.mkdir()
    source_pdf = legal_dir / "Article 302.pdf"
    source_pdf.write_bytes(b"PDF fixture")

    class SessionStub:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback):
            assert _exc_type is None
            assert _exc_value is None
            assert _traceback is None
            return False

        def commit(self):
            pass

    def load_staged_corpus(_session, pdf_dir: Path, **kwargs):
        assert _session is not None
        staged_pdf = pdf_dir / source_pdf.name
        assert staged_pdf.is_file()
        assert not staged_pdf.is_symlink()
        assert staged_pdf.read_bytes() == source_pdf.read_bytes()
        assert callable(kwargs["embed_fn"])
        return 0

    monkeypatch.setattr(corpus, "LEGAL_DIR", legal_dir)
    monkeypatch.setattr(corpus, "PGM_FILES", ("Article 302.pdf",))
    monkeypatch.setattr(corpus, "MANIFEST", ())
    monkeypatch.setattr(corpus, "Session", Mock(return_value=SessionStub()))
    monkeypatch.setattr(corpus, "load_corpus_from_directory", load_staged_corpus)

    assert corpus.build_corpus(object(), Mock(), log=Mock()) == ([], 0)
