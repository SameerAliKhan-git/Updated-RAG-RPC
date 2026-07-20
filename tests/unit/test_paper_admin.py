"""Corpus — Paper deletion fan-out unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.services.paper_admin import delete_paper_everywhere


def _patch_pdf(exists: bool):
    """Patch the PDF path so no real filesystem is touched; returns (ctx, unlink_mock)."""
    pdf_path = MagicMock()
    pdf_path.exists.return_value = exists
    ctx = patch("src.services.paper_admin.Path")
    return ctx, pdf_path


def test_delete_raises_lookup_error_when_paper_missing():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(LookupError):
        delete_paper_everywhere(db, MagicMock(), "0000.00000")


def test_delete_fans_out_to_every_store():
    """Deletion must hit OpenSearch, the concept-graph rows, the PDF, and finally
    Postgres — a paper left in any one store resurfaces in search/galaxy/viewer."""
    paper = MagicMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = paper
    db.query.return_value.filter.return_value.delete.return_value = 2

    opensearch = MagicMock()
    opensearch.delete_by_query.return_value = {"deleted": 7}

    ctx, pdf_path = _patch_pdf(exists=True)
    with ctx as mock_path_cls:
        mock_path_cls.return_value.__truediv__.return_value = pdf_path
        summary = delete_paper_everywhere(db, opensearch, "1706.03762")

    opensearch.delete_by_query.assert_called_once()
    assert summary["opensearch_deleted"] == 7
    db.delete.assert_called_once_with(paper)
    db.commit.assert_called_once()
    assert summary["pdf_deleted"] is True
    pdf_path.unlink.assert_called_once()
    assert summary["errors"] == []


def test_delete_is_best_effort_when_opensearch_fails():
    """An OpenSearch outage must not block removing the source-of-truth row —
    the failure is recorded, and Postgres deletion still happens."""
    paper = MagicMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = paper
    db.query.return_value.filter.return_value.delete.return_value = 0

    opensearch = MagicMock()
    opensearch.delete_by_query.side_effect = ConnectionError("opensearch down")

    ctx, pdf_path = _patch_pdf(exists=False)
    with ctx as mock_path_cls:
        mock_path_cls.return_value.__truediv__.return_value = pdf_path
        summary = delete_paper_everywhere(db, opensearch, "1706.03762")

    assert any("opensearch" in e for e in summary["errors"])
    db.delete.assert_called_once_with(paper)
    db.commit.assert_called_once()
