"""Private curriculum object storage. No bucket or filesystem path is exposed to clients."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

import boto3

from app.config import Settings


class ObjectStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = None
        if settings.object_storage_provider == "r2":
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )

    def put_file(self, key: str, source: Path) -> None:
        if self.client:
            self.client.upload_file(str(source), self.settings.r2_bucket, key)
            return
        target = (self.settings.object_storage_directory / key).resolve()
        root = self.settings.object_storage_directory.resolve()
        if root not in target.parents:
            raise ValueError("Invalid object key")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def open(self, key: str) -> BinaryIO:
        if self.client:
            return self.client.get_object(Bucket=self.settings.r2_bucket, Key=key)["Body"]
        target = (self.settings.object_storage_directory / key).resolve()
        if self.settings.object_storage_directory.resolve() not in target.parents:
            raise ValueError("Invalid object key")
        return target.open("rb")

    def delete(self, key: str) -> None:
        if self.client:
            self.client.delete_object(Bucket=self.settings.r2_bucket, Key=key)
            return
        target = (self.settings.object_storage_directory / key).resolve()
        if self.settings.object_storage_directory.resolve() not in target.parents:
            raise ValueError("Invalid object key")
        target.unlink(missing_ok=True)
