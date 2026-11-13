"""파일 저장소 경계. 업무 로직은 이 인터페이스만 쓰고, Supabase Storage로 옮길 때 구현체만 바꾼다.

DB(files 테이블)에는 절대 경로 대신 storage_kind + object_key를 기록한다.
"""

import hashlib
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID

from app.core.config import get_settings

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class StoredObject:
    storage_kind: str
    object_key: str
    size_bytes: int
    sha256: str


class FileStorage(Protocol):
    kind: str

    def put(self, owner_id: UUID, stream: BinaryIO, max_bytes: int) -> StoredObject: ...

    def open(self, object_key: str) -> BinaryIO: ...

    def delete(self, object_key: str) -> None: ...

    def presign(self, object_key: str, expires_seconds: int) -> str | None:
        """짧은 유효기간 다운로드 URL. 지원하지 않으면 None → API가 직접 스트리밍한다."""
        ...


class FileTooLargeError(Exception):
    pass


class LocalFileStorage:
    kind = "local"

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        path = (self.root / object_key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("object key escapes storage root")
        return path

    def put(self, owner_id: UUID, stream: BinaryIO, max_bytes: int) -> StoredObject:
        object_key = f"{owner_id}/{uuid.uuid4().hex}"
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        tmp = path.with_suffix(".part")
        try:
            with tmp.open("xb") as out:
                while chunk := stream.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError
                    digest.update(chunk)
                    out.write(chunk)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return StoredObject(self.kind, object_key, size, digest.hexdigest())

    def open(self, object_key: str) -> BinaryIO:
        return self._path(object_key).open("rb")

    def delete(self, object_key: str) -> None:
        self._path(object_key).unlink(missing_ok=True)

    def presign(self, object_key: str, expires_seconds: int) -> str | None:
        return None


@lru_cache
def get_storage() -> FileStorage:
    return LocalFileStorage(get_settings().storage_root)
