import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skills.vivarium.vivarium_v2.canonical import canonical_bytes
from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import Event, ZERO_HASH
from skills.vivarium.vivarium_v2.ledger import Ledger


def build_event(sequence: int, previous: str, *, ledger_id: str = "project-work") -> Event:
    return Event.build(
        ledger_id=ledger_id,
        event_seq=sequence,
        event_id=f"evt-{sequence:04d}",
        event_type="WORK_LEDGER_GENESIS" if sequence == 0 else "WORK_RECORDED",
        tx_id=f"tx-{sequence:04d}",
        prev_event_hash=previous,
        recorded_at=f"2026-07-18T00:00:{sequence:02d}Z",
        effective_at=f"2026-07-18T00:00:{sequence:02d}Z",
        payload={"sequence": sequence},
    )


def corrupt_line(event: Event) -> bytes:
    record = json.loads(event.to_line())
    record["event_id"] += "-corrupt"
    return canonical_bytes(record) + b"\n"


class LedgerRecoveryTests(unittest.TestCase):
    def test_append_two_events_and_recover_chain(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work.jsonl"
            ledger = Ledger(path, "project-work")
            first = build_event(0, ZERO_HASH)
            second = build_event(1, first.event_hash)

            ledger.append(first)
            ledger.append(second)
            result = ledger.recover()

            self.assertEqual(result.events, (first, second))
            self.assertEqual(result.quarantined_tail, b"")

    def test_missing_final_lf_quarantines_only_last_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "work.jsonl"
            ledger = Ledger(path, "project-work")
            first = build_event(0, ZERO_HASH)
            second = build_event(1, first.event_hash)
            ledger.append(first)
            ledger.append(second)
            original = path.read_bytes()
            path.write_bytes(original[:-1])

            result = ledger.recover()

            self.assertEqual(result.events, (first,))
            self.assertEqual(result.quarantined_tail, second.to_line()[:-1])
            self.assertEqual(path.read_bytes(), original[:-1])

    def test_quarantine_tail_is_durable_content_addressed_and_non_mutating(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "work.jsonl"
            quarantine_dir = root / "quarantine"
            ledger = Ledger(path, "project-work")
            first = build_event(0, ZERO_HASH)
            path.write_bytes(first.to_line()[:-1])
            before = path.read_bytes()
            digest = hashlib.sha256(before).hexdigest()

            stored = ledger.quarantine_tail(quarantine_dir)
            stored_again = ledger.quarantine_tail(quarantine_dir)

            self.assertEqual(stored, quarantine_dir / f"sha256-{digest}.tail")
            self.assertEqual(stored_again, stored)
            self.assertEqual(stored.read_bytes(), before)
            self.assertEqual(path.read_bytes(), before)

    def test_quarantine_tail_returns_none_for_clean_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Ledger(Path(td) / "work.jsonl", "project-work")
            self.assertIsNone(ledger.quarantine_tail(Path(td) / "quarantine"))

    def test_corrupt_middle_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work.jsonl"
            first = build_event(0, ZERO_HASH)
            second = build_event(1, first.event_hash)
            path.write_bytes(corrupt_line(first) + second.to_line())

            with self.assertRaises(IntegrityError):
                Ledger(path, "project-work").recover()

    def test_complete_invalid_final_record_is_quarantined(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work.jsonl"
            event = build_event(0, ZERO_HASH)
            invalid_line = corrupt_line(event)
            path.write_bytes(invalid_line)

            result = Ledger(path, "project-work").recover()

            self.assertEqual(result.events, ())
            self.assertEqual(result.quarantined_tail, invalid_line)

    def test_complete_invalid_record_followed_by_any_byte_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work.jsonl"
            event = build_event(0, ZERO_HASH)
            path.write_bytes(corrupt_line(event) + b"x")

            with self.assertRaises(IntegrityError):
                Ledger(path, "project-work").recover()

    def test_repeated_recovery_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work.jsonl"
            ledger = Ledger(path, "project-work")
            first = build_event(0, ZERO_HASH)
            ledger.append(first)
            before = path.read_bytes()

            one = ledger.recover()
            two = ledger.recover()

            self.assertEqual(one, two)
            self.assertEqual(path.read_bytes(), before)

    def test_append_syncs_file_and_new_directory_before_success(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger" / "work.jsonl"
            ledger = Ledger(path, "project-work")
            real_fsync = os.fsync
            synced_modes = []

            def recording_fsync(fd):
                synced_modes.append(os.fstat(fd).st_mode)
                return real_fsync(fd)

            with patch(
                "skills.vivarium.vivarium_v2.ledger.os.fsync",
                side_effect=recording_fsync,
            ):
                ledger.append(build_event(0, ZERO_HASH))

            self.assertGreaterEqual(len(synced_modes), 2)

    def test_append_does_not_report_success_when_file_sync_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Ledger(Path(td) / "work.jsonl", "project-work")
            with patch(
                "skills.vivarium.vivarium_v2.ledger.os.fsync",
                side_effect=OSError("injected sync failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected sync failure"):
                    ledger.append(build_event(0, ZERO_HASH))

    def test_append_requires_previous_event_hash_not_record_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Ledger(Path(td) / "work.jsonl", "project-work")
            first = build_event(0, ZERO_HASH)
            ledger.append(first)
            wrong_second = build_event(1, first.record_checksum)

            with self.assertRaises(IntegrityError):
                ledger.append(wrong_second)

            self.assertEqual(ledger.recover().events, (first,))

    def test_append_refuses_unresolved_torn_tail(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work.jsonl"
            first = build_event(0, ZERO_HASH)
            path.write_bytes(first.to_line()[:-1])

            with self.assertRaises(IntegrityError):
                Ledger(path, "project-work").append(first)


if __name__ == "__main__":
    unittest.main()
