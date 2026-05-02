"""Data Storage — persistence layer for crawled data.

Supports local file, MinIO (S3-compatible Data Lake), and multiple formats.
"""

from __future__ import annotations

import json
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models.request import OutputDestination, OutputFormat
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DataStorage:
    """Save processed data to various destinations and formats."""

    def __init__(self):
        self.settings = get_settings()
        self._minio_client = None

    def save(
        self,
        records: list[dict[str, Any]],
        request_id: str,
        format: OutputFormat = OutputFormat.JSON,
        destination: OutputDestination = OutputDestination.DATA_LAKE,
    ) -> str:
        """
        Save records to the configured destination.

        Returns:
            Path or URI where data was saved.
        """
        # Serialize data
        data_bytes = self._serialize(records, format)
        filename = self._build_filename(request_id, format)

        if destination == OutputDestination.LOCAL_FILE:
            return self._save_local(data_bytes, filename)
        elif destination in (OutputDestination.S3, OutputDestination.DATA_LAKE):
            return self._save_minio(data_bytes, filename, bucket=self.settings.minio_bucket_clean)
        else:
            return self._save_local(data_bytes, filename)

    def save_audit(self, audit_data: dict[str, Any], request_id: str) -> str:
        """Save audit log to data lake."""
        data = json.dumps(audit_data, indent=2, default=str, ensure_ascii=False).encode("utf-8")
        filename = f"audit/{request_id}.json"
        try:
            return self._save_minio(data, filename, bucket=self.settings.minio_bucket_audit)
        except Exception:
            return self._save_local(data, f"logs/{filename}")

    def _serialize(self, records: list[dict[str, Any]], format: OutputFormat) -> bytes:
        """Serialize records to the requested format."""
        if format == OutputFormat.JSON:
            return json.dumps(records, indent=2, default=str, ensure_ascii=False).encode("utf-8")

        elif format == OutputFormat.CSV:
            if not records:
                return b""
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
            return output.getvalue().encode("utf-8")

        elif format == OutputFormat.PARQUET:
            import pandas as pd
            import pyarrow as pa
            import pyarrow.parquet as pq
            df = pd.DataFrame(records)
            buf = io.BytesIO()
            table = pa.Table.from_pandas(df)
            pq.write_table(table, buf)
            return buf.getvalue()

        elif format == OutputFormat.DELTA:
            # Delta Lake via deltalake library
            import pandas as pd
            from deltalake.writer import write_deltalake
            df = pd.DataFrame(records)
            delta_path = str(self.settings.project_root / "data" / "delta")
            Path(delta_path).mkdir(parents=True, exist_ok=True)
            write_deltalake(delta_path, df, mode="append")
            return b""  # Delta writes directly to disk

        return json.dumps(records, default=str).encode("utf-8")

    def _build_filename(self, request_id: str, format: OutputFormat) -> str:
        """Build output filename with timestamp."""
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        ext = format.value
        if ext == "delta":
            ext = "parquet"
        return f"data/{ts}_{request_id[:8]}.{ext}"

    def _save_local(self, data: bytes, filename: str) -> str:
        """Save to local filesystem."""
        path = self.settings.project_root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.info(f"Saved locally: {path}")
        return str(path)

    def _save_minio(self, data: bytes, filename: str, bucket: str) -> str:
        """Save to MinIO (S3-compatible) data lake."""
        client = self._get_minio_client()
        # Ensure bucket exists
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        data_stream = io.BytesIO(data)
        client.put_object(
            bucket_name=bucket,
            object_name=filename,
            data=data_stream,
            length=len(data),
            content_type="application/octet-stream",
        )
        uri = f"s3://{bucket}/{filename}"
        logger.info(f"Saved to MinIO: {uri}")
        return uri

    def _get_minio_client(self):
        """Get or create MinIO client."""
        if self._minio_client is None:
            from minio import Minio
            self._minio_client = Minio(
                self.settings.minio_endpoint,
                access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key,
                secure=self.settings.minio_use_ssl,
            )
        return self._minio_client
