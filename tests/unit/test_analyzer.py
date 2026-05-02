"""Unit tests for Phase 0 — Web Analyzer."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.analyzer import WebAnalyzer
from src.models.request import CrawlRequest, DataSpec, DataType, TargetInfo, WebType


def _make_request(url: str = "https://example.com") -> CrawlRequest:
    return CrawlRequest(
        target=TargetInfo(url=url),
        data_spec=DataSpec(data_type=DataType.CUSTOM),
    )


class TestWebAnalyzer:
    """Test web type classification logic."""

    @pytest.mark.asyncio
    async def test_detect_static_site(self):
        """Plain HTML should be classified as STATIC."""
        analyzer = WebAnalyzer()
        mock_response = MagicMock()
        mock_response.text = "<html><body><h1>Hello</h1><p>Simple page</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.status_code = 200

        with patch.object(analyzer.http_client, "fetch", new_callable=AsyncMock, return_value=mock_response):
            request = _make_request()
            result = await analyzer.analyze(request)
            assert result.web_type == WebType.STATIC

    @pytest.mark.asyncio
    async def test_detect_dynamic_site(self):
        """React/Vue app should be classified as DYNAMIC."""
        analyzer = WebAnalyzer()
        mock_response = MagicMock()
        mock_response.text = '''
            <html><body>
            <div id="root"></div>
            <script src="react.js"></script>
            <script>window.__NEXT_DATA__ = {};</script>
            </body></html>
        '''
        mock_response.headers = {"content-type": "text/html"}
        mock_response.status_code = 200

        with patch.object(analyzer.http_client, "fetch", new_callable=AsyncMock, return_value=mock_response):
            request = _make_request()
            result = await analyzer.analyze(request)
            assert result.web_type == WebType.DYNAMIC

    @pytest.mark.asyncio
    async def test_detect_api_based(self):
        """JSON API response should be classified as API_BASED."""
        analyzer = WebAnalyzer()
        mock_response = MagicMock()
        mock_response.text = '{"data": [], "total": 0}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.status_code = 200

        with patch.object(analyzer.http_client, "fetch", new_callable=AsyncMock, return_value=mock_response):
            request = _make_request("https://api.example.com/v1/products")
            result = await analyzer.analyze(request)
            assert result.web_type == WebType.API_BASED

    @pytest.mark.asyncio
    async def test_detect_paginated(self):
        """Page with pagination links should be classified as PAGINATED."""
        analyzer = WebAnalyzer()
        mock_response = MagicMock()
        mock_response.text = '''
            <html><body>
            <div class="products"><div class="item">Product 1</div></div>
            <a href="?page=2">Next</a>
            </body></html>
        '''
        mock_response.headers = {"content-type": "text/html"}
        mock_response.status_code = 200

        with patch.object(analyzer.http_client, "fetch", new_callable=AsyncMock, return_value=mock_response):
            request = _make_request("https://shop.example.com/products?page=1")
            result = await analyzer.analyze(request)
            assert result.web_type == WebType.PAGINATED
