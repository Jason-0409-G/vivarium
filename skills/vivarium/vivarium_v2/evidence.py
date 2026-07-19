from __future__ import annotations

import base64
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .canonical import canonical_bytes, domain_hash, durable_replace
from .errors import IntegrityError


EVIDENCE_BUNDLE_SCHEMA = "vivarium.evidence-bundle/v1"
VALIDATOR_SEAL_SCHEMA = "vivarium.validator-seal/v1"
WRITER_CLOSURE_DOMAIN = "vivarium-writer-closure/v1"
REVOCATION_DOMAIN = "vivarium-capability-revocation-receipt/v1"


def _is_digest(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@dataclass(frozen=True, order=True)
class EvidenceFile:
    relative_path: str
    content_digest: str
    size: int
    artifact_path: str


@dataclass(frozen=True)
class EvidenceBundle:
    schema_version: str
    run_id: str
    stage_id: str
    attempt_id: str
    execution_intent_id: str
    execution_evidence_cut_digest: str
    payload_manifest: tuple[EvidenceFile, ...]
    log_manifest: tuple[EvidenceFile, ...]
    writer_closure_digest: str
    capability_revocation_receipt_digest: str
    sealed_by_role: str

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_BUNDLE_SCHEMA:
            raise IntegrityError("evidence bundle schema is unsupported")
        for field in (
            self.execution_evidence_cut_digest,
            self.writer_closure_digest,
            self.capability_revocation_receipt_digest,
        ):
            if not _is_digest(field):
                raise IntegrityError("evidence bundle contains an invalid digest")
        if self.payload_manifest != tuple(sorted(self.payload_manifest)):
            raise IntegrityError("payload manifest is not canonically sorted")
        if self.log_manifest != tuple(sorted(self.log_manifest)):
            raise IntegrityError("log manifest is not canonically sorted")
        if self.sealed_by_role != "validator":
            raise IntegrityError("only the validator may seal authoritative evidence roots")

    def canonical_body(self) -> dict[str, Any]:
        entry = lambda item: {
            "relative_path": item.relative_path,
            "content_digest": item.content_digest,
            "size": item.size,
            "artifact_path": item.artifact_path,
        }
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "attempt_id": self.attempt_id,
            "execution_intent_id": self.execution_intent_id,
            "execution_evidence_cut_digest": self.execution_evidence_cut_digest,
            "payload_manifest": [entry(item) for item in self.payload_manifest],
            "log_manifest": [entry(item) for item in self.log_manifest],
            "writer_closure_digest": self.writer_closure_digest,
            "capability_revocation_receipt_digest": self.capability_revocation_receipt_digest,
            "sealed_by_role": self.sealed_by_role,
        }

    @property
    def evidence_bundle_digest(self) -> str:
        return domain_hash("vivarium-evidence-bundle/v1", self.canonical_body())


@dataclass(frozen=True)
class ValidatorSeal:
    schema_version: str
    evidence_bundle_digest: str
    execution_evidence_cut_digest: str
    validator_id: str
    validation_outcome: str
    validation_report_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != VALIDATOR_SEAL_SCHEMA:
            raise IntegrityError("validator seal schema is unsupported")
        if self.validation_outcome not in {"pass", "repairable", "scientifically_invalid"}:
            raise IntegrityError("validator seal outcome is not closed")
        if not all(
            _is_digest(value)
            for value in (
                self.evidence_bundle_digest,
                self.execution_evidence_cut_digest,
                self.validation_report_digest,
            )
        ):
            raise IntegrityError("validator seal contains an invalid digest")

    def canonical_body(self) -> dict[str, str]:
        return asdict(self)

    @property
    def validator_seal_digest(self) -> str:
        return domain_hash("vivarium-validator-seal/v1", self.canonical_body())


def persist_writer_closure(store: Any, body: Mapping[str, Any]) -> str:
    value = dict(body)
    digest = domain_hash(WRITER_CLOSURE_DOMAIN, value)
    durable_replace(
        Path(store.root) / "artifacts" / f"{digest[7:]}.writer-closure.json",
        canonical_bytes(value),
    )
    return digest


def _canonical_object(
    store: Any, digest: str, suffix: str, domain: str
) -> dict[str, Any]:
    if not _is_digest(digest):
        raise IntegrityError("closure object digest is invalid")
    path = Path(store.root) / "artifacts" / f"{digest[7:]}.{suffix}.json"
    try:
        raw = path.read_bytes()
        body = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError("closure object is not durably resolvable") from exc
    if (
        not isinstance(body, dict)
        or canonical_bytes(body) != raw
        or domain_hash(domain, body) != digest
    ):
        raise IntegrityError("closure object bytes do not match their digest")
    return body


def _relative_parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise IntegrityError("evidence path must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise IntegrityError("evidence path escapes the project root")
    return path.parts


def _secure_read(root: Path, relative_path: str) -> bytes:
    parts = _relative_parts(relative_path)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    root_fd = os.open(root, os.O_RDONLY | directory)
    current_fd = root_fd
    opened_directories: list[int] = []
    file_fd = None
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=current_fd,
                )
            except OSError as exc:
                raise IntegrityError("evidence directory traversal is not no-follow safe") from exc
            opened_directories.append(next_fd)
            current_fd = next_fd
        try:
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NONBLOCK | nofollow,
                dir_fd=current_fd,
            )
        except OSError as exc:
            raise IntegrityError("evidence target cannot be opened without following links") from exc
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise IntegrityError("evidence target must be a single-link regular file")
        chunks = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(file_fd)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
        )
        if identity(before) != identity(after):
            raise IntegrityError("evidence target changed while it was being sealed")
        return b"".join(chunks)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for fd in reversed(opened_directories):
            os.close(fd)
        os.close(root_fd)


def _seal_files(
    store: Any, relative_paths: Sequence[str], allowed_prefix: str
) -> tuple[EvidenceFile, ...]:
    if isinstance(relative_paths, (str, bytes)):
        raise IntegrityError("evidence manifest inputs must be a path sequence")
    prefix_parts = _relative_parts(allowed_prefix)
    normalized = tuple(relative_paths)
    if len(normalized) != len(set(normalized)):
        raise IntegrityError("evidence manifest paths must be unique")
    entries = []
    for relative_path in normalized:
        parts = _relative_parts(relative_path)
        if (
            len(parts) <= len(prefix_parts)
            or parts[: len(prefix_parts)] != prefix_parts
        ):
            raise IntegrityError("evidence path is outside the attempt workspace")
        body = _secure_read(Path(store.root), relative_path)
        content_digest = domain_hash(
            "vivarium-evidence-file/v1", base64.b64encode(body).decode("ascii")
        )
        artifact_path = f"artifacts/evidence-files/{content_digest[7:]}.blob"
        destination = Path(store.root) / artifact_path
        if destination.exists():
            if destination.read_bytes() != body:
                raise IntegrityError("content-addressed evidence bytes disagree")
        else:
            durable_replace(destination, body)
        entries.append(
            EvidenceFile(relative_path, content_digest, len(body), artifact_path)
        )
    return tuple(sorted(entries))


def seal_evidence_bundle(
    store: Any,
    *,
    run_id: str,
    stage_id: str,
    attempt_id: str,
    execution_intent_id: str,
    execution_evidence_cut_digest: str,
    payload_paths: Sequence[str],
    log_paths: Sequence[str],
    writer_closure_digest: str,
    capability_revocation_receipt_digest: str,
    authority_role: str,
) -> EvidenceBundle:
    if authority_role != "validator":
        raise IntegrityError("Maker cannot supply authoritative evidence roots")
    writer = _canonical_object(
        store, writer_closure_digest, "writer-closure", WRITER_CLOSURE_DOMAIN
    )
    revocation = _canonical_object(
        store,
        capability_revocation_receipt_digest,
        "capability-revocation",
        REVOCATION_DOMAIN,
    )
    expected_identity = {
        "run_id": run_id,
        "stage_id": stage_id,
        "attempt_id": attempt_id,
        "execution_intent_id": execution_intent_id,
    }
    if any(writer.get(field) != value for field, value in expected_identity.items()) or writer.get(
        "writer_closed"
    ) is not True:
        raise IntegrityError("writer closure does not bind the sealed execution")
    if any(revocation.get(field) != value for field, value in expected_identity.items()) or revocation.get(
        "revoked"
    ) is not True:
        raise IntegrityError("capability revocation does not bind the sealed execution")
    allowed_prefix = f"runs/{run_id}/attempts/{stage_id}/{attempt_id}"
    bundle = EvidenceBundle(
        EVIDENCE_BUNDLE_SCHEMA,
        run_id,
        stage_id,
        attempt_id,
        execution_intent_id,
        execution_evidence_cut_digest,
        _seal_files(store, payload_paths, allowed_prefix),
        _seal_files(store, log_paths, allowed_prefix),
        writer_closure_digest,
        capability_revocation_receipt_digest,
        authority_role,
    )
    path = (
        Path(store.root)
        / "artifacts"
        / "evidence-bundles"
        / f"{bundle.evidence_bundle_digest[7:]}.json"
    )
    durable_replace(path, canonical_bytes(bundle.canonical_body()))
    validate_evidence_bundle(store, bundle)
    return bundle


def validate_evidence_bundle(
    store: Any,
    bundle: EvidenceBundle,
    *,
    expected_evidence_cut_digest: str | None = None,
) -> None:
    if not isinstance(bundle, EvidenceBundle):
        raise IntegrityError("evidence validation requires an immutable bundle")
    if (
        expected_evidence_cut_digest is not None
        and bundle.execution_evidence_cut_digest != expected_evidence_cut_digest
    ):
        raise IntegrityError("evidence bundle is stale for the expected execution cut")
    bundle_path = (
        Path(store.root)
        / "artifacts"
        / "evidence-bundles"
        / f"{bundle.evidence_bundle_digest[7:]}.json"
    )
    try:
        if bundle_path.read_bytes() != canonical_bytes(bundle.canonical_body()):
            raise IntegrityError("durable evidence bundle bytes were tampered")
    except OSError as exc:
        raise IntegrityError("durable evidence bundle is missing") from exc
    for item in (*bundle.payload_manifest, *bundle.log_manifest):
        path = Path(store.root) / item.artifact_path
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise IntegrityError("content-addressed evidence artifact is missing") from exc
        digest = domain_hash(
            "vivarium-evidence-file/v1", base64.b64encode(body).decode("ascii")
        )
        if digest != item.content_digest or len(body) != item.size:
            raise IntegrityError("content-addressed evidence artifact was tampered")
    _canonical_object(
        store, bundle.writer_closure_digest, "writer-closure", WRITER_CLOSURE_DOMAIN
    )
    _canonical_object(
        store,
        bundle.capability_revocation_receipt_digest,
        "capability-revocation",
        REVOCATION_DOMAIN,
    )


def seal_validator_evidence(
    store: Any,
    bundle: EvidenceBundle,
    *,
    validator_id: str,
    validation_outcome: str,
    findings: Mapping[str, Any],
) -> ValidatorSeal:
    validate_evidence_bundle(store, bundle)
    report = {
        "validator_id": validator_id,
        "validation_outcome": validation_outcome,
        "evidence_bundle_digest": bundle.evidence_bundle_digest,
        "execution_evidence_cut_digest": bundle.execution_evidence_cut_digest,
        "findings": dict(findings),
    }
    report_digest = domain_hash("vivarium-validator-report/v1", report)
    durable_replace(
        Path(store.root) / "artifacts" / f"{report_digest[7:]}.validator-report.json",
        canonical_bytes(report),
    )
    seal = ValidatorSeal(
        VALIDATOR_SEAL_SCHEMA,
        bundle.evidence_bundle_digest,
        bundle.execution_evidence_cut_digest,
        validator_id,
        validation_outcome,
        report_digest,
    )
    durable_replace(
        Path(store.root) / "artifacts" / f"{seal.validator_seal_digest[7:]}.validator-seal.json",
        canonical_bytes(seal.canonical_body()),
    )
    return seal


__all__ = [
    "EVIDENCE_BUNDLE_SCHEMA",
    "VALIDATOR_SEAL_SCHEMA",
    "EvidenceBundle",
    "EvidenceFile",
    "ValidatorSeal",
    "persist_writer_closure",
    "seal_evidence_bundle",
    "seal_validator_evidence",
    "validate_evidence_bundle",
]
