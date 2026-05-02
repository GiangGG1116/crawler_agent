"""Unit tests for Phase 3 — Data Processing pipeline."""

import pytest
from src.processing.cleaner import DataCleaner
from src.processing.deduplicator import Deduplicator
from src.processing.scorer import QualityScorer
from src.processing.validator import SchemaValidator
from src.models.request import CrawlRequest, DataSpec, DataType, TargetInfo


class TestDataCleaner:
    def test_strip_whitespace(self):
        cleaner = DataCleaner()
        assert cleaner.clean_value("  hello  ") == "hello"

    def test_strip_html(self):
        cleaner = DataCleaner()
        assert cleaner.clean_value("<b>Bold</b> text", "description") == "Bold text"

    def test_parse_currency(self):
        cleaner = DataCleaner()
        assert cleaner.clean_value("$1,299.00", "price") == 1299.0

    def test_parse_date(self):
        cleaner = DataCleaner()
        result = cleaner.clean_value("May 1, 2026", "publish_date")
        assert result == "2026-05-01"

    def test_normalize_url(self):
        cleaner = DataCleaner(base_url="https://example.com")
        assert cleaner.clean_value("/products/1", "url") == "https://example.com/products/1"

    def test_none_passthrough(self):
        cleaner = DataCleaner()
        assert cleaner.clean_value(None) is None

    def test_clean_records(self):
        cleaner = DataCleaner()
        records = [{"title": "  Test  ", "price": "$9.99"}, {"title": None}]
        cleaned = cleaner.clean_records(records)
        assert len(cleaned) == 2
        assert cleaned[0]["title"] == "Test"


class TestDeduplicator:
    def test_remove_exact_duplicates(self):
        dedup = Deduplicator()
        records = [{"a": 1}, {"a": 1}, {"a": 2}]
        unique, removed = dedup.deduplicate(records)
        assert len(unique) == 2
        assert removed == 1

    def test_key_field_dedup(self):
        dedup = Deduplicator(key_fields=["id"])
        records = [{"id": 1, "x": "a"}, {"id": 1, "x": "b"}, {"id": 2, "x": "c"}]
        unique, removed = dedup.deduplicate(records)
        assert len(unique) == 2

    def test_no_duplicates(self):
        dedup = Deduplicator()
        records = [{"a": 1}, {"a": 2}, {"a": 3}]
        unique, removed = dedup.deduplicate(records)
        assert len(unique) == 3
        assert removed == 0


class TestQualityScorer:
    def test_perfect_score(self):
        scorer = QualityScorer()
        records = [{"name": "A", "price": 10}, {"name": "B", "price": 20}]
        report = scorer.score(records, total_before_dedup=2, required_fields=["name", "price"])
        assert report.overall_score >= 90
        assert report.grade.value == "excellent"

    def test_low_completeness(self):
        scorer = QualityScorer()
        records = [{"name": None, "price": None}, {"name": "B", "price": None}]
        report = scorer.score(records, total_before_dedup=2, required_fields=["name", "price"])
        assert report.completeness_score < 50

    def test_dedup_penalty(self):
        scorer = QualityScorer()
        records = [{"name": "A"}]
        report = scorer.score(records, total_before_dedup=10, required_fields=["name"])
        assert report.uniqueness_score == 10.0  # 1/10 * 100


class TestSchemaValidator:
    def test_valid_records(self):
        validator = SchemaValidator()
        request = CrawlRequest(
            target=TargetInfo(url="https://example.com"),
            data_spec=DataSpec(data_type=DataType.PRODUCTS, required_fields=["name", "price"]),
        )
        records = [{"name": "Item", "price": 10}, {"name": "Item2", "price": 20}]
        result = validator.validate(records, request)
        assert result.is_valid is True

    def test_empty_records(self):
        validator = SchemaValidator()
        request = CrawlRequest(
            target=TargetInfo(url="https://example.com"),
            data_spec=DataSpec(data_type=DataType.PRODUCTS, required_fields=["name"]),
        )
        result = validator.validate([], request)
        assert result.is_valid is False

    def test_missing_required_fields(self):
        validator = SchemaValidator()
        request = CrawlRequest(
            target=TargetInfo(url="https://example.com"),
            data_spec=DataSpec(data_type=DataType.PRODUCTS, required_fields=["name", "price"]),
        )
        records = [{"name": None, "price": None} for _ in range(10)]
        result = validator.validate(records, request)
        assert result.is_valid is False
