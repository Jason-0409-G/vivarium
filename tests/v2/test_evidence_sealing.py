import os
import socket
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from skills.vivarium.vivarium_v2.canonical import domain_hash
from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.evidence import (
    seal_evidence_bundle,
    seal_validator_evidence,
    validate_evidence_bundle,
)
from tests.v2.support import evidence_sealing_fixture


class EvidenceSealingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _fixture(self, name):
        return evidence_sealing_fixture(self.root / name)

    def _seal(self, fixture, **overrides):
        values = {
            **fixture["identity"],
            "execution_evidence_cut_digest": fixture[
                "execution_evidence_cut_digest"
            ],
            "payload_paths": fixture["payload_paths"],
            "log_paths": fixture["log_paths"],
            "writer_closure_digest": fixture["writer_closure_digest"],
            "capability_revocation_receipt_digest": fixture[
                "capability_revocation_receipt_digest"
            ],
            "authority_role": "validator",
        }
        values.update(overrides)
        return seal_evidence_bundle(fixture["store"], **values)

    def test_regular_files_are_content_addressed_and_manifests_are_canonical(self):
        fixture = self._fixture("valid")
        bundle = self._seal(fixture)
        validate_evidence_bundle(fixture["store"], bundle)

        self.assertEqual(bundle.payload_manifest, tuple(sorted(bundle.payload_manifest)))
        self.assertEqual(bundle.log_manifest, tuple(sorted(bundle.log_manifest)))
        for item in (*bundle.payload_manifest, *bundle.log_manifest):
            self.assertTrue((fixture["store"].root / item.artifact_path).is_file())
        seal = seal_validator_evidence(
            fixture["store"],
            bundle,
            validator_id="validator-1",
            validation_outcome="pass",
            findings={"hard_gates": "pass"},
        )
        self.assertEqual(seal.evidence_bundle_digest, bundle.evidence_bundle_digest)
        with self.assertRaises(FrozenInstanceError):
            bundle.run_id = "other"

    def test_no_follow_reader_rejects_links_special_files_and_escape(self):
        fixture = self._fixture("unsafe")
        directory = fixture["directory"]
        regular = directory / "a-result.txt"
        symlink = directory / "symlink.txt"
        symlink.symlink_to(regular)
        hardlink = directory / "hardlink.txt"
        os.link(regular, hardlink)
        fifo = directory / "pipe"
        os.mkfifo(fifo)
        socket_path = fixture["store"].root / "s"
        unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_socket.bind(str(socket_path))
        try:
            unsafe = (
                symlink.relative_to(fixture["store"].root).as_posix(),
                hardlink.relative_to(fixture["store"].root).as_posix(),
                fifo.relative_to(fixture["store"].root).as_posix(),
                socket_path.relative_to(fixture["store"].root).as_posix(),
                "/dev/null",
                "../outside.txt",
            )
            for path in unsafe:
                with self.subTest(path=path), self.assertRaises(IntegrityError):
                    self._seal(fixture, payload_paths=(path,))
        finally:
            unix_socket.close()

    def test_closure_authority_and_tamper_bindings_are_fail_closed(self):
        fixture = self._fixture("binding")
        with self.assertRaises(IntegrityError):
            self._seal(fixture, authority_role="maker")
        with self.assertRaises(IntegrityError):
            self._seal(
                fixture,
                writer_closure_digest=domain_hash("vivarium-missing/v1", {}),
            )
        bundle = self._seal(fixture)
        with self.assertRaises(IntegrityError):
            validate_evidence_bundle(
                fixture["store"],
                bundle,
                expected_evidence_cut_digest=domain_hash("vivarium-stale-cut/v1", {}),
            )
        forged = replace(
            bundle,
            execution_evidence_cut_digest=domain_hash("vivarium-forged-cut/v1", {}),
        )
        with self.assertRaises(IntegrityError):
            validate_evidence_bundle(fixture["store"], forged)
        artifact = fixture["store"].root / bundle.payload_manifest[0].artifact_path
        artifact.write_bytes(b"tampered\n")
        with self.assertRaises(IntegrityError):
            validate_evidence_bundle(fixture["store"], bundle)

    def test_evidence_digest_binds_provenance(self):
        # M-13 (audit): the same payload sealed under different provenance
        # (code/environment/request/key material) must yield a different
        # evidence identity, so a stale review/cache cannot be mis-bound.
        fixture = self._fixture("prov")
        base = self._seal(fixture)
        other = self._seal(fixture, provenance_digest="sha256:" + "a" * 64)
        self.assertNotEqual(base.provenance_digest, other.provenance_digest)
        self.assertNotEqual(
            base.evidence_bundle_digest, other.evidence_bundle_digest
        )

    def test_sealer_rejects_paths_outside_the_attempt_workspace(self):
        # M-15 (audit): the snapshotter was scoped to the whole project root, so
        # it could seal another run's private data or a mutable projection. Only
        # files under this attempt's workspace subtree may be sealed.
        fixture = self._fixture("scope")
        outside = fixture["store"].root / "sneak.txt"
        outside.write_bytes(b"other-run-secret\n")
        with self.assertRaises(IntegrityError):
            self._seal(fixture, payload_paths=("sneak.txt",))


if __name__ == "__main__":
    unittest.main()
