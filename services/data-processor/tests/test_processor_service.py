"""Unit tests for data-processor service."""

from __future__ import annotations

from src.processing.cleaner import DataCleaner
from src.processing.deduplicator import Deduplicator
from src.processing.scorer import QualityScorer


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "data-processor"


class TestDataCleaner:
    def test_strip_whitespace(self):
        cleaner = DataCleaner()
        records = [{"title": "  hello world  ", "url": "  https://example.com  "}]
        result = cleaner.clean(records)
        assert result[0]["title"] == "hello world"
        assert result[0]["url"] == "https://example.com"

    def test_remove_html_tags(self):
        cleaner = DataCleaner()
        records = [{"title": "<b>Hello</b> <i>World</i>"}]
        result = cleaner.clean(records)
        assert result[0]["title"] == "Hello World"

    def test_discard_empty_records(self):
        cleaner = DataCleaner()
        records = [
            {"title": "valid", "url": "https://example.com"},
            {"title": "", "url": ""},
        ]
        result = cleaner.clean(records)
        assert len(result) == 1


class TestDeduplicator:
    def test_removes_exact_duplicates(self):
        dedup = Deduplicator()
        records = [
            {"title": "a", "url": "1"},
            {"title": "a", "url": "1"},
            {"title": "b", "url": "2"},
        ]
        result = dedup.deduplicate(records)
        assert len(result) == 2

    def test_preserves_unique_records(self):
        dedup = Deduplicator()
        records = [
            {"title": "a", "url": "1"},
            {"title": "b", "url": "2"},
        ]
        result = dedup.deduplicate(records)
        assert len(result) == 2


class TestQualityScorer:
    def test_perfect_score(self):
        scorer = QualityScorer()
        records = [
            {"title": "a", "url": "1", "date": "2024-01-01"},
            {"title": "b", "url": "2", "date": "2024-01-02"},
        ]
        report = scorer.score(
            raw_count=2,
            clean_count=2,
            rejected_count=0,
            required_fields=["title", "url"],
            records=records,
        )
        assert report.completeness_score == 100.0
        assert report.overall_score > 80.0

    def test_low_completeness(self):
        scorer = QualityScorer()
        records = [
            {"title": "a", "url": ""},
            {"title": "", "url": "2"},
        ]
        report = scorer.score(
            raw_count=2,
            clean_count=2,
            rejected_count=0,
            required_fields=["title", "url"],
            records=records,
        )
        assert report.completeness_score == 0.0
