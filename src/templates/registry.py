"""Template Registry — lookup and management of scraper templates.

Central registry that maps (web_type, data_type) → Template for Phase 1 fast path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.models.request import DataType, WebType
from src.templates.base_template import BaseTemplate, TemplateConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TemplateRegistry:
    """
    Registry of available scraper templates.

    Usage:
        registry = TemplateRegistry()
        registry.auto_register()  # Load all built-in templates
        template, config = registry.lookup(WebType.STATIC, DataType.ARTICLES)
    """

    def __init__(self):
        self._templates: dict[str, type[BaseTemplate]] = {}
        self._configs: dict[str, TemplateConfig] = {}
        self._web_type_map: dict[WebType, list[str]] = {}

    def register(self, template_cls: type[BaseTemplate], config: TemplateConfig | None = None) -> None:
        """Register a template class with optional config."""
        template_id = template_cls.template_id
        self._templates[template_id] = template_cls

        # Map web type → template IDs
        web_type = template_cls.web_type
        if web_type not in self._web_type_map:
            self._web_type_map[web_type] = []
        if template_id not in self._web_type_map[web_type]:
            self._web_type_map[web_type].append(template_id)

        if config:
            self._configs[template_id] = config

        logger.info(f"Registered template: {template_id} ({template_cls.template_name}) for {web_type.value}")

    def auto_register(self, configs_dir: Path | None = None) -> None:
        """
        Auto-register all built-in templates and load their JSON configs.
        """
        # Import all template classes
        from src.templates.static_scraper import StaticScraper
        from src.templates.dynamic_scraper import DynamicScraper
        from src.templates.api_scraper import APIScraper
        from src.templates.paginated_scraper import PaginatedScraper
        from src.templates.auth_scraper import AuthScraper

        all_templates = [StaticScraper, DynamicScraper, APIScraper, PaginatedScraper, AuthScraper]

        for template_cls in all_templates:
            self.register(template_cls)

        # Load JSON configs if available
        if configs_dir:
            self._load_configs(configs_dir)

    def _load_configs(self, configs_dir: Path) -> None:
        """Load template JSON config files from directory."""
        if not configs_dir.exists():
            logger.warning(f"Template configs directory not found: {configs_dir}")
            return

        for config_file in sorted(configs_dir.glob("*.json")):
            try:
                config = TemplateConfig.from_json_file(config_file)
                self._configs[config.template_id] = config
                logger.debug(f"Loaded config: {config_file.name} → {config.template_id}")
            except Exception as e:
                logger.warning(f"Failed to load config {config_file}: {e}")

    def lookup(
        self,
        web_type: WebType,
        data_type: DataType | None = None,
    ) -> tuple[BaseTemplate, TemplateConfig | None]:
        """
        Find the best template for a given web type and data type.

        Args:
            web_type: Classified website type from Phase 0.
            data_type: Type of data to extract (used for config selection).

        Returns:
            Tuple of (template_instance, config_or_None).

        Raises:
            KeyError: If no template found for the web type.
        """
        template_ids = self._web_type_map.get(web_type, [])
        if not template_ids:
            raise KeyError(f"No template registered for web_type={web_type.value}")

        # Use first matching template (priority order by registration)
        template_id = template_ids[0]
        template_cls = self._templates[template_id]
        config = self._configs.get(template_id)

        logger.info(f"Lookup: {web_type.value} → {template_id}")
        return template_cls(config=config), config

    def get_template(self, template_id: str) -> tuple[BaseTemplate, TemplateConfig | None]:
        """Get a specific template by ID."""
        if template_id not in self._templates:
            raise KeyError(f"Template not found: {template_id}")
        template_cls = self._templates[template_id]
        config = self._configs.get(template_id)
        return template_cls(config=config), config

    def list_all(self) -> list[dict[str, Any]]:
        """List all registered templates."""
        result = []
        for tid, tcls in self._templates.items():
            result.append({
                "template_id": tid,
                "template_name": tcls.template_name,
                "web_type": tcls.web_type.value,
                "tool_stack": tcls.tool_stack,
                "has_config": tid in self._configs,
            })
        return result
