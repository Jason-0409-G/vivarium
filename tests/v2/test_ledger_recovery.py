import hashlib
import json
import os
import stat
import tempfile
import threading
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

    def test_first_creator_holds_writer_lock_through_directory_sync(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger" / "work.jsonl"
            first = build_event(0, ZERO_HASH)
            second = build_event(1, first.event_hash)
            real_fsync = os.fsync

            import fcntl

            real_flock = fcntl.flock
            directory_sync_entered = threading.Event()
            allow_directory_sync = threading.Event()
            writer_b_started = threading.Event()
            writer_b_returned = threading.Event()
            ordering = []
            ordering_lock = threading.Lock()
            thread_errors = []

            def record(label):
                with ordering_lock:
                    ordering.append(label)

            def controlled_fsync(fd):
                writer = threading.current_thread().name
                mode = os.fstat(fd).st_mode
                if stat.S_ISDIR(mode):
                    record(f"{writer}:directory_fsync_start")
                    if writer == "writer-a":
                        directory_sync_entered.set()
                        if not allow_directory_sync.wait(2):
                            raise AssertionError("directory fsync gate timed out")
                    result = real_fsync(fd)
                    record(f"{writer}:directory_fsync_done")
                    return result
                if stat.S_ISREG(mode):
                    record(f"{writer}:file_fsync")
                    return real_fsync(fd)
                raise AssertionError("fsync called for unexpected descriptor type")

            def recording_flock(fd, operation):
                result = real_flock(fd, operation)
                writer = threading.current_thread().name
                if operation == fcntl.LOCK_EX:
                    record(f"{writer}:lock_acquired")
                elif operation == fcntl.LOCK_UN:
                    record(f"{writer}:unlock")
                return result

            def append_as(writer, event, returned, started=None):
                if started is not None:
                    started.set()
                try:
                    Ledger(path, "project-work").append(event)
                except BaseException as exc:
                    thread_errors.append((writer, exc))
                else:
                    record(f"{writer}:return")
                    returned.set()

            writer_a_returned = threading.Event()
            writer_a = threading.Thread(
                target=append_as,
                args=("writer-a", first, writer_a_returned),
                name="writer-a",
            )
            writer_b = threading.Thread(
                target=append_as,
                args=("writer-b", second, writer_b_returned, writer_b_started),
                name="writer-b",
            )

            with patch(
                "skills.vivarium.vivarium_v2.ledger.os.fsync",
                side_effect=controlled_fsync,
            ), patch(
                "skills.vivarium.vivarium_v2.ledger.fcntl.flock",
                side_effect=recording_flock,
            ):
                writer_a.start()
                try:
                    self.assertTrue(
                        directory_sync_entered.wait(2),
                        f"writer A did not reach directory fsync: {ordering}",
                    )
                    writer_b.start()
                    self.assertTrue(writer_b_started.wait(2))
                    returned_before_directory_sync = writer_b_returned.wait(0.25)
                finally:
                    allow_directory_sync.set()
                    writer_a.join(2)
                    if writer_b.ident is not None:
                        writer_b.join(2)

            self.assertFalse(writer_a.is_alive(), ordering)
            self.assertFalse(writer_b.is_alive(), ordering)
            self.assertEqual(thread_errors, [])
            self.assertFalse(
                returned_before_directory_sync,
                f"writer B returned before writer A's directory fsync: {ordering}",
            )

            def position(label):
                return ordering.index(label)

            self.assertLess(
                position("writer-a:file_fsync"),
                position("writer-a:directory_fsync_start"),
            )
            self.assertLess(
                position("writer-a:directory_fsync_done"),
                position("writer-a:unlock"),
            )
            self.assertLess(
                position("writer-a:unlock"), position("writer-a:return")
            )
            self.assertLess(
                position("writer-a:unlock"), position("writer-b:lock_acquired")
            )
            self.assertLess(
                position("writer-b:file_fsync"), position("writer-b:unlock")
            )
            self.assertLess(
                position("writer-b:unlock"), position("writer-b:return")
            )

    def test_append_does_not_report_success_when_file_sync_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Ledger(Path(td) / "work.jsonl", "project-work")
            with patch(
                "skills.vivarium.vivarium_v2.ledger.os.fsync",
                side_effect=OSError("injected sync failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected sync failure"):
                    ledger.append(build_event(0, ZERO_HASH))

    def test_quarantine_tail_syncs_file_then_directory_before_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "work.jsonl"
            quarantine_dir = root / "quarantine"
            ledger = Ledger(path, "project-work")
            path.write_bytes(build_event(0, ZERO_HASH).to_line()[:-1])
            real_fsync = os.fsync
            sync_order = []

            def recording_fsync(fd):
                mode = os.fstat(fd).st_mode
                if stat.S_ISREG(mode):
                    sync_order.append("file")
                elif stat.S_ISDIR(mode):
                    sync_order.append("directory")
                else:
                    self.fail("fsync called for unexpected descriptor type")
                return real_fsync(fd)

            with patch(
                "skills.vivarium.vivarium_v2.canonical.os.fsync",
                side_effect=recording_fsync,
            ):
                stored = ledger.quarantine_tail(quarantine_dir)

            self.assertEqual(sync_order, ["file", "directory"])
            self.assertTrue(stored.is_file())

    def test_quarantine_tail_sync_failures_raise_and_leave_ledger_unchanged(self):
        for failing_kind in ("file", "directory"):
            with self.subTest(failing_kind=failing_kind):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    path = root / "work.jsonl"
                    ledger = Ledger(path, "project-work")
                    path.write_bytes(build_event(0, ZERO_HASH).to_line()[:-1])
                    before = path.read_bytes()
                    real_fsync = os.fsync
                    observed = []

                    def failing_fsync(fd):
                        mode = os.fstat(fd).st_mode
                        kind = "directory" if stat.S_ISDIR(mode) else "file"
                        observed.append(kind)
                        if kind == failing_kind:
                            raise OSError(f"injected {kind} sync failure")
                        return real_fsync(fd)

                    with patch(
                        "skills.vivarium.vivarium_v2.canonical.os.fsync",
                        side_effect=failing_fsync,
                    ):
                        with self.assertRaisesRegex(
                            OSError, f"injected {failing_kind} sync failure"
                        ):
                            ledger.quarantine_tail(root / "quarantine")

                    self.assertIn(failing_kind, observed)
                    self.assertEqual(path.read_bytes(), before)

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
