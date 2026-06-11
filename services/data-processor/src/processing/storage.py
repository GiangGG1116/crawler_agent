"""DataStorage — persists processed data to MinIO data lake.

Supports JSON, CSV, and Parquet output formats.
Also stores audit logs.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

from shared.models.audit import AuditLog
from shared.utils.config import Settings
from shared.utils.logger import get_logger

logger = get_logger(__name__)


class DataStorage:
    """MinIO-backed data storage for processed crawl results."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

    def _get_client(self):
        """Lazy-initialize MinIO client."""
        if not self._client:
            from minio import Minio

            self._client = Minio(
                self._settings.minio_endpoint,
                access_key=self._settings.minio_access_key,
                secret_key=self._settings.minio_secret_key,
                secure=self._settings.minio_use_ssl,
            )
        return self._client

    async def store(
        self,
        request_id: str,
        records: list[dict[str, Any]],
        output_format: str = "json",
        output_destination: str = "data_lake",
    ) -> str | None:
        """Store processed records to MinIO."""
        if not records:
            return None

        try:
            client = self._get_client()
            bucket = self._settings.minio_bucket_clean
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            base_path = f"{request_id}/{timestamp}"

            # Ensure bucket exists
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

            if output_format == "json":
                return self._store_json(client, bucket, base_path, records)
            elif output_format == "csv":
                return self._store_csv(client, bucket, base_path, records)
            elif output_format == "parquet":
                return self._store_parquet(client, bucket, base_path, records)
            else:
                return self._store_json(client, bucket, base_path, records)

        except Exception as e:
            logger.error("Storage failed: %s", e)
            return None

    def _store_json(self, client, bucket: str, base_path: str, records) -> str:
        """Store as JSON."""
        object_name = f"{base_path}/data.json"
        data = json.dumps(records, default=str, ensure_ascii=False, indent=2)
        data_bytes = data.encode("utf-8")
        client.put_object(
            bucket,
            object_name,
            io.BytesIO(data_bytes),
            length=len(data_bytes),
            content_type="application/json",
        )
        path = f"s3://{bucket}/{object_name}"
        logger.info("Stored JSON: %s (%d records)", path, len(records))
        return path

    def _store_csv(self, client, bucket: str, base_path: str, records) -> str:
        """Store as CSV."""
        import csv

        object_name = f"{base_path}/data.csv"
        output = io.StringIO()
        if records:
            writer = csv.DictWriter(output, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
        data_bytes = output.getvalue().encode("utf-8")
        client.put_object(
            bucket,
            object_name,
            io.BytesIO(data_bytes),
            length=len(data_bytes),
            content_type="text/csv",
        )
        path = f"s3://{bucket}/{object_name}"
        logger.info("Stored CSV: %s (%d records)", path, len(records))
        return path

    def _store_parquet(self, client, bucket: str, base_path: str, records) -> str:
        """Store as Parquet."""
        import pandas as pd

        object_name = f"{base_path}/data.parquet"
        df = pd.DataFrame(records)
        buffer = io.BytesIO()
        df.to_parquet(buffer, engine="pyarrow", index=False)
        data_bytes = buffer.getvalue()
        client.put_object(
            bucket,
            object_name,
            io.BytesIO(data_bytes),
            length=len(data_bytes),
            content_type="application/octet-stream",
        )
        path = f"s3://{bucket}/{object_name}"
        logger.info("Stored Parquet: %s (%d records)", path, len(records))
        return path

    async def store_audit(self, audit: AuditLog) -> None:
        """Store audit log to MinIO."""
        try:
            client = self._get_client()
            bucket = self._settings.minio_bucket_audit

            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

            object_name = f"{audit.request_id}/{audit.audit_id}.json"
            data = json.dumps(audit.model_dump(mode="json"), default=str, indent=2)
            data_bytes = data.encode("utf-8")
            client.put_object(
                bucket,
                object_name,
                io.BytesIO(data_bytes),
                length=len(data_bytes),
                content_type="application/json",
            )
            logger.info("Stored audit: %s", object_name)

        except Exception as e:
            logger.error("Audit storage failed: %s", e)
