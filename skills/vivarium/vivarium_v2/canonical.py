from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import IntegrityError


MIN_INTEROPERABLE_INTEGER = -(2**53) + 1
MAX_INTEROPERABLE_INTEGER = 2**53 - 1


def _validate(value: Any, active_containers: set[int] | None = None) -> None:
    if active_containers is None:
        active_containers = set()
    if isinstance(value, float):
        raise IntegrityError(
            "floating JSON values are forbidden; use canonical decimal strings"
        )
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise IntegrityError("lone surrogate code points are forbidden") from exc
        return
    if isinstance(value, int):
        if not MIN_INTEROPERABLE_INTEGER <= value <= MAX_INTEROPERABLE_INTEGER:
            raise IntegrityError("integer outside interoperable range")
        return
    if isinstance(value, (list, dict)):
        marker = id(value)
        if marker in active_containers:
            raise IntegrityError("cyclic canonical JSON value")
        active_containers.add(marker)
        try:
            if isinstance(value, list):
                for item in value:
                    _validate(item, active_containers)
                return
            if not all(isinstance(key, str) for key in value):
                raise IntegrityError("canonical JSON object keys must be strings")
            for key, item in value.items():
                _validate(key, active_containers)
                _validate(item, active_containers)
            return
        finally:
            active_containers.remove(marker)
    raise IntegrityError(f"unsupported canonical JSON value: {type(value).__name__}")


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be")


def _ordered(value: Any) -> Any:
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _ordered(value[key])
            for key in sorted(value, key=_utf16_sort_key)
        }
    return value


def canonical_bytes(value: Any) -> bytes:
    _validate(value)
    return json.dumps(
        _ordered(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def domain_hash(domain: str, value: Any) -> str:
    if not isinstance(domain, str):
        raise IntegrityError("hash domain must be a string")
    try:
        prefix = domain.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise IntegrityError("hash domain contains a lone surrogate") from exc
    body = prefix + b"\x00" + canonical_bytes(value)
    return "sha256:" + hashlib.sha256(body).hexdigest()


def durable_replace(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if os.path.exists(name):
            failed = path.parent / ".failed-staging"
            failed.mkdir(exist_ok=True)
            os.replace(name, failed / Path(name).name)
        raise
