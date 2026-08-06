"""对象存储：storage_path 用相对根目录的 posix 路径存库，URL 由 /media/{path} 派生。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from .config import settings


class StorageError(Exception):
    pass


def validate_storage_path(storage_path: str, expected_prefix: str | None = None) -> str:
    if (
        not isinstance(storage_path, str)
        or not storage_path
        or "\\" in storage_path
        or "\x00" in storage_path
        or Path(storage_path).is_absolute()
    ):
        raise ValueError("Invalid storage path")
    relative = PurePosixPath(storage_path)
    if ".." in relative.parts:
        raise ValueError("Invalid storage path")
    if expected_prefix is not None:
        prefix = PurePosixPath(expected_prefix)
        if relative.parts[: len(prefix.parts)] != prefix.parts:
            raise ValueError("Invalid storage path")
    return str(relative)


class LocalObjectStorage:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.media_root)

    def _path(self, storage_path: str) -> Path:
        storage_path = validate_storage_path(storage_path)
        root = self.root.resolve()
        target = (root / Path(*PurePosixPath(storage_path).parts)).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Invalid storage path")
        return target

    def save(self, storage_path: str, data: bytes) -> None:
        target = self._path(storage_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read(self, storage_path: str) -> bytes:
        target = self._path(storage_path)
        if not target.is_file():
            raise FileNotFoundError(storage_path)
        return target.read_bytes()

    def size(self, storage_path: str) -> int:
        target = self._path(storage_path)
        if not target.is_file():
            raise FileNotFoundError(storage_path)
        return target.stat().st_size

    def delete(self, storage_path: str) -> None:
        try:
            self._path(storage_path).unlink(missing_ok=True)
        except OSError:
            pass

    @contextmanager
    def local_path(self, storage_path: str):
        target = self._path(storage_path)
        if not target.is_file():
            raise FileNotFoundError(storage_path)
        yield target


_storage: LocalObjectStorage | None = None


def get_storage() -> LocalObjectStorage:
    global _storage
    if _storage is None:
        _storage = LocalObjectStorage()
    return _storage


def url_for(storage_path: str) -> str:
    return f"/media/{validate_storage_path(storage_path)}"
