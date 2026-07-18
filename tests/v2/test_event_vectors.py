import json
import unittest

from skills.vivarium.vivarium_v2.canonical import canonical_bytes
from skills.vivarium.vivarium_v2.errors import IntegrityError
from skills.vivarium.vivarium_v2.events import Event, ZERO_HASH


G1_PAYLOAD = {
    "activated_objects": [],
    "canonical_dependency_edges": [],
    "initial_state_root": "sha256:" + "1" * 64,
}


def build_g1() -> Event:
    return Event.build(
        ledger_id="project-work",
        event_seq=0,
        event_id="evt-0000",
        event_type="WORK_LEDGER_GENESIS",
        tx_id="tx-0000",
        prev_event_hash=ZERO_HASH,
        recorded_at="2026-07-18T00:00:00Z",
        effective_at="2026-07-18T00:00:00Z",
        payload=G1_PAYLOAD,
    )


class EventVectorTests(unittest.TestCase):
    def test_g1(self):
        event = build_g1()

        self.assertEqual(
            event.payload_hash,
            "sha256:00c6aae330bb591495f6a07e1beb11acd28dc05947746e8cb17f948a0acf5cd5",
        )
        self.assertEqual(
            event.event_hash,
            "sha256:6565f908781a7c60faf4a0e9d2ecf1d14d23e717d5484482d6c4be25c84286d9",
        )
        self.assertEqual(
            event.record_checksum,
            "sha256:1bc5c8af19320b330995dab649e8d3b668cd3394bbf4ccdb02ef507876f53e70",
        )
        self.assertTrue(event.to_line().endswith(b"\n"))

    def test_g2(self):
        event = Event.build(
            ledger_id="project-truth",
            event_seq=0,
            event_id="evt-truth-0000",
            event_type="TRUTH_LEDGER_GENESIS",
            tx_id="tx-truth-0000",
            prev_event_hash=ZERO_HASH,
            recorded_at="2026-07-18T01:02:03Z",
            effective_at="2026-07-18T01:02:03Z",
            payload={
                "activated_objects": [],
                "canonical_dependency_edges": [],
                "initial_state_root": "sha256:" + "2" * 64,
            },
        )

        self.assertEqual(
            event.payload_hash,
            "sha256:c914049f521ee0456b48ee8d9d6c19b1e5dcb5e2d689cf74cfa6c9c61f31737b",
        )
        self.assertEqual(
            event.event_hash,
            "sha256:6165124d51df520259aef0ba47459ea97a5633c0e539165ddd61387959734ef0",
        )
        self.assertEqual(
            event.record_checksum,
            "sha256:68b6f64e88d53fa1d22794a6520850acddf89e2ba5cc48a2b4058fdbcdefcc84",
        )

    def test_from_line_rejects_crlf(self):
        with self.assertRaises(IntegrityError):
            Event.from_line(build_g1().to_line()[:-1] + b"\r\n")

    def test_from_line_rejects_missing_final_lf(self):
        with self.assertRaises(IntegrityError):
            Event.from_line(build_g1().to_line()[:-1])

    def test_from_line_rejects_extra_field(self):
        record = json.loads(build_g1().to_line())
        record["extra"] = "forbidden"

        with self.assertRaises(IntegrityError):
            Event.from_line(canonical_bytes(record) + b"\n")

    def test_build_rejects_float(self):
        with self.assertRaises(IntegrityError):
            Event.build(
                ledger_id="project-work",
                event_seq=0,
                event_id="evt-float",
                event_type="WORK_LEDGER_GENESIS",
                tx_id="tx-float",
                prev_event_hash=ZERO_HASH,
                recorded_at="2026-07-18T00:00:00Z",
                effective_at="2026-07-18T00:00:00Z",
                payload={"score": 1.5},
            )

    def test_build_rejects_bad_genesis_prev_hash(self):
        with self.assertRaises(IntegrityError):
            Event.build(
                ledger_id="project-work",
                event_seq=0,
                event_id="evt-bad-prev",
                event_type="WORK_LEDGER_GENESIS",
                tx_id="tx-bad-prev",
                prev_event_hash="sha256:" + "f" * 64,
                recorded_at="2026-07-18T00:00:00Z",
                effective_at="2026-07-18T00:00:00Z",
                payload={},
            )

    def test_canonical_keys_use_utf16_code_unit_order(self):
        self.assertEqual(
            canonical_bytes({"\ue000": 1, "\U00010000": 2}),
            '{"\U00010000":2,"\ue000":1}'.encode("utf-8"),
        )

    def test_canonical_json_rejects_lone_surrogates(self):
        for value in ({"value": "\ud800"}, {"\udfff": "value"}):
            with self.subTest(value=value):
                with self.assertRaises(IntegrityError):
                    canonical_bytes(value)


if __name__ == "__main__":
    unittest.main()
