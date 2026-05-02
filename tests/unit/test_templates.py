"""Unit tests for template registry and base template functionality."""

import pytest
from src.templates.registry import TemplateRegistry
from src.models.request import WebType, DataType


class TestTemplateRegistry:
    def test_auto_register(self):
        registry = TemplateRegistry()
        registry.auto_register()
        templates = registry.list_all()
        assert len(templates) >= 5

    def test_lookup_static(self):
        registry = TemplateRegistry()
        registry.auto_register()
        template, config = registry.lookup(WebType.STATIC)
        assert template.template_id == "TPL-001"

    def test_lookup_dynamic(self):
        registry = TemplateRegistry()
        registry.auto_register()
        template, config = registry.lookup(WebType.DYNAMIC)
        assert template.template_id == "TPL-002"

    def test_lookup_api(self):
        registry = TemplateRegistry()
        registry.auto_register()
        template, config = registry.lookup(WebType.API_BASED)
        assert template.template_id == "TPL-003"

    def test_lookup_missing_type_raises(self):
        registry = TemplateRegistry()
        with pytest.raises(KeyError):
            registry.lookup(WebType.STATIC)  # No templates registered

    def test_get_template_by_id(self):
        registry = TemplateRegistry()
        registry.auto_register()
        template, _ = registry.get_template("TPL-001")
        assert template.template_name == "static_article_scraper"
