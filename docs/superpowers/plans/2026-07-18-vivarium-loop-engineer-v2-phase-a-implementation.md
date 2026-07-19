# Vivarium Loop Engineer V2 Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reversible, event-sourced Phase A Loop Engineer with isolated Maker/Checker gates, drift-resistant project context, bioinformatics contracts, and a static/fake cluster layer while keeping every real cluster mutation disabled.

**Architecture:** Add a standard-library Python package beside the existing umbrella skill and keep `scripts/orchestrate.py` as a compatibility entry point. Canonical ledgers and immutable content objects are authoritative; reducers, manifests, SQLite, and handoff text are rebuildable projections. Deliver the system in independently reviewable vertical slices, with fault tests written before each implementation.

**Tech Stack:** Python 3.11+ standard library (`argparse`, `dataclasses`, `enum`, `hashlib`, `json`, `fcntl`, `os`, `pathlib`, `tempfile`, `unittest`); JSONL ledgers; RFC-8785-compatible restricted canonical JSON; POSIX `fsync`/advisory locks; existing shell/Python/R bioinformatics scripts.

## Global Constraints

- The reviewed design is `docs/superpowers/specs/2026-07-18-vivarium-loop-engineer-v2-design.md`; implementation must not weaken any hard gate.
- Phase A real `submit/cancel/hold/release/smoke` is disabled. Static detection may `stat/open/read/hash` executable bytes but must never execute `qsub`, `csub`, `qdel`, or scheduler help/version probes.
- GPTomics/bioSkills is design-study material only. No runtime, build, installation, import, catalog, test, vendor, generated-source, or benchmark dependency is allowed.
- Do not auto-install Python, conda, Homebrew, scheduler, or bioinformatics packages.
- Use append-only events and content-addressed objects. Never overwrite or delete canonical history; cleanup uses the repository's approved soft-trash mechanism.
- Preserve legacy `init/status/update` behavior until the V2 migration tests pass. Legacy `--force` remains backup-first.
- Maker, Validator, and Checker cannot write canonical ledgers or active heads. Soft isolation always blocks automatic commit.
- Exact ledger hash constants G1/G2 and the three array/gather roots are copied from the reviewed spec and hard-coded in tests.
- Every task follows RED → GREEN → focused regression → commit. Do not combine tasks into one unreviewed change.

---

## File and responsibility map

| Path | Responsibility |
|---|---|
| `skills/vivarium/vivarium_v2/canonical.py` | Restricted canonical JSON, domain-separated hashes, atomic durable file writes |
| `skills/vivarium/vivarium_v2/events.py` | Fixed event envelope and G1/G2 encoding |
| `skills/vivarium/vivarium_v2/ledger.py` | Append, fsync, locking, recovery, torn-tail quarantine |
| `skills/vivarium/vivarium_v2/state.py` | Closed enums, reducer outputs, abort reason map |
| `skills/vivarium/vivarium_v2/schemas/state_machine.yaml` | Machine-source transition table encoded as strict JSON/YAML subset |
| `skills/vivarium/vivarium_v2/reducers.py` | Run, five project, project-validity, run-validity, federated reducers |
| `skills/vivarium/vivarium_v2/project.py` | Project/run initialization, complete-cut transactions, recovery, rollback/fork |
| `skills/vivarium/vivarium_v2/execution.py` | Agent-only/local intents, supervised process receipts, completion classification/proofs |
| `skills/vivarium/vivarium_v2/evidence.py` | Content objects, evidence bundles, validator/review sealing |
| `skills/vivarium/vivarium_v2/roles.py` | Maker/Checker assignments, capability receipts, quorum policy |
| `skills/vivarium/vivarium_v2/knowledge.py` | Fact/decision/memory heads, invalidation, sealed-history retrieval |
| `skills/vivarium/vivarium_v2/handoff.py` | `HandoffSnapshot` and deterministic bounded projection |
| `skills/vivarium/vivarium_v2/bio/contracts.py` | Typed biological/statistical/database contracts |
| `skills/vivarium/vivarium_v2/bio/validators.py` | Deterministic bioinformatics hard gates |
| `skills/vivarium/vivarium_v2/cluster/profiles.py` | qsub/csub static profile schemas and render rules |
| `skills/vivarium/vivarium_v2/cluster/arrays.py` | Array manifest, native binding, task and gather identities |
| `skills/vivarium/vivarium_v2/cluster/static.py` | Non-executing detection, fingerprint, lint, render |
| `skills/vivarium/vivarium_v2/cluster/fake.py` | In-memory fake scheduler and invocation counters |
| `skills/vivarium/vivarium_v2/cli.py` | V2 CLI routing and structured exit codes |
| `skills/vivarium/scripts/orchestrate.py` | Legacy-compatible executable wrapper |
| `tests/v2/` | Unit, model, fault-injection, migration, and end-to-end tests |

### Task 1: Freeze legacy behavior and create the V2 package boundary

**Files:**
- Create: `skills/vivarium/vivarium_v2/__init__.py`
- Create: `skills/vivarium/vivarium_v2/errors.py`
- Create: `skills/vivarium/vivarium_v2/cli.py`
- Create: `tests/v2/test_legacy_compatibility.py`
- Create: `tests/v2/test_cli_boundary.py`
- Modify: `skills/vivarium/scripts/orchestrate.py:1-176`

**Interfaces:**
- Consumes: current `DAGS`, `cmd_init`, `cmd_status`, and `cmd_update` behavior.
- Produces: `vivarium_v2.cli.main(argv: Sequence[str] | None) -> int`, `VivariumError`, `IntegrityError`, `PolicyError`, and a wrapper that routes legacy commands unchanged.

- [ ] **Step 1: Write characterization tests for the current CLI**

```python
# tests/v2/test_legacy_compatibility.py
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path("skills/vivarium/scripts/orchestrate.py")

class LegacyCompatibilityTests(unittest.TestCase):
    def test_init_status_update_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            genomes = root / "genomes"
            genomes.mkdir()
            (genomes / "a.fna").write_text(">a\nACGT\n", encoding="utf-8")
            init = subprocess.run(
                ["python3", str(SCRIPT), "init", "--goal", "compare-genomes",
                 "--indir", str(genomes), "--workdir", str(root)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            manifest = root / "vivarium_run_compare-genomes" / "run_manifest.json"
            body = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual([s["status"] for s in body["stages"]], ["planned"] * 4)

            update = subprocess.run(
                ["python3", str(SCRIPT), "update", "--manifest", str(manifest),
                 "--stage", "1", "--status", "done", "--command", "seqkit stats",
                 "--version", "seqkit 2.8"],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(update.returncode, 0, update.stderr)
            self.assertEqual(json.loads(manifest.read_text())["stages"][0]["status"], "done")
```

- [ ] **Step 2: Run the characterization test**

Run: `python3 -m unittest tests.v2.test_legacy_compatibility -v`

Expected: PASS on the unmodified legacy implementation.

- [ ] **Step 3: Add the package error types and an explicit V2 CLI boundary**

```python
# skills/vivarium/vivarium_v2/errors.py
class VivariumError(Exception):
    exit_code = 2

class IntegrityError(VivariumError):
    exit_code = 3

class PolicyError(VivariumError):
    exit_code = 4

class RecoveryRequired(VivariumError):
    exit_code = 5
```

```python
# skills/vivarium/vivarium_v2/cli.py
from __future__ import annotations
from collections.abc import Sequence
from .errors import VivariumError

def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv or ())
    if not args:
        raise VivariumError("V2 command required")
    raise VivariumError(f"unknown V2 command: {args[0]}")
```

```python
# skills/vivarium/vivarium_v2/__init__.py
__version__ = "2.0.0a1"
```

- [ ] **Step 4: Refactor the script without changing the three legacy command paths**

Move existing parser construction into `legacy_main(argv)` and add a top-level dispatch with this exact rule:

```python
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["v2"]:
        skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if skill_root not in sys.path:
            sys.path.insert(0, skill_root)
        from vivarium_v2.cli import main as v2_main
        raise SystemExit(v2_main(argv[1:]))
    legacy_main(argv)
```

- [ ] **Step 5: Run legacy and boundary tests**

Run: `python3 -m unittest tests.v2.test_legacy_compatibility tests.v2.test_cli_boundary -v`

Expected: legacy round-trip PASS; `v2` with no subcommand exits with the documented V2 error code and never edits a manifest.

- [ ] **Step 6: Commit the package boundary**

```bash
git add skills/vivarium/scripts/orchestrate.py skills/vivarium/vivarium_v2 tests/v2
git commit -m "refactor: add vivarium v2 package boundary"
```

### Task 2: Implement canonical events and durable ledgers

**Files:**
- Create: `skills/vivarium/vivarium_v2/canonical.py`
- Create: `skills/vivarium/vivarium_v2/events.py`
- Create: `skills/vivarium/vivarium_v2/ledger.py`
- Create: `tests/v2/test_event_vectors.py`
- Create: `tests/v2/test_ledger_recovery.py`

**Interfaces:**
- Consumes: Task 1 error types.
- Produces: `canonical_bytes(value)`, `domain_hash(domain, value)`, `Event.build`, `Event.to_line`, `Ledger.append(event)`, and `Ledger.recover()`.

- [ ] **Step 1: Write failing golden-vector tests**

```python
# tests/v2/test_event_vectors.py
import unittest
from skills.vivarium.vivarium_v2.events import Event

class EventVectorTests(unittest.TestCase):
    def test_g1(self):
        event = Event.build(
            ledger_id="project-work", event_seq=0, event_id="evt-0000",
            event_type="WORK_LEDGER_GENESIS", tx_id="tx-0000",
            prev_event_hash="sha256:" + "0" * 64,
            recorded_at="2026-07-18T00:00:00Z",
            effective_at="2026-07-18T00:00:00Z",
            payload={"activated_objects": [], "canonical_dependency_edges": [],
                     "initial_state_root": "sha256:" + "1" * 64},
        )
        self.assertEqual(event.payload_hash, "sha256:00c6aae330bb591495f6a07e1beb11acd28dc05947746e8cb17f948a0acf5cd5")
        self.assertEqual(event.event_hash, "sha256:6565f908781a7c60faf4a0e9d2ecf1d14d23e717d5484482d6c4be25c84286d9")
        self.assertEqual(event.record_checksum, "sha256:1bc5c8af19320b330995dab649e8d3b668cd3394bbf4ccdb02ef507876f53e70")
        self.assertTrue(event.to_line().endswith(b"\n"))
```

Add G2 with the three constants from §7.1 and negative cases for CRLF, a missing final LF, an extra field, a float, and a bad `prev_event_hash`.

- [ ] **Step 2: Run the vector test to verify RED**

Run: `python3 -m unittest tests.v2.test_event_vectors -v`

Expected: FAIL because `events.py` does not exist.

- [ ] **Step 3: Implement restricted canonical JSON and the fixed envelope**

```python
# skills/vivarium/vivarium_v2/canonical.py
from __future__ import annotations
import hashlib, json, os, tempfile
from pathlib import Path
from typing import Any
from .errors import IntegrityError

def _validate(value: Any) -> None:
    if isinstance(value, float):
        raise IntegrityError("floating JSON values are forbidden; use canonical decimal strings")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, int) and not (-(2**53) < value < 2**53):
            raise IntegrityError("integer outside interoperable range")
        return
    if isinstance(value, list):
        for item in value: _validate(item)
        return
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for item in value.values(): _validate(item)
        return
    raise IntegrityError(f"unsupported canonical JSON value: {type(value).__name__}")

def canonical_bytes(value: Any) -> bytes:
    _validate(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def domain_hash(domain: str, value: Any) -> str:
    body = domain.encode("utf-8") + b"\x00" + canonical_bytes(value)
    return "sha256:" + hashlib.sha256(body).hexdigest()

def durable_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    except BaseException:
        if os.path.exists(name):
            failed = path.parent / ".failed-staging"
            failed.mkdir(exist_ok=True)
            os.replace(name, failed / Path(name).name)
        raise
```

Implement `Event` as a frozen dataclass whose `build` method validates the exact top-level field set, UTC-second timestamps, genesis sequence, and all three hashes. `from_line` must reject bytes that are not exactly `canonical_bytes(record) + b"\n"`.

- [ ] **Step 4: Write ledger crash/recovery tests**

Create tests that append two valid events, then test: missing final LF quarantines only the last record; a corrupt middle record fails closed; repeated recovery is byte-identical; appending requires `fdatasync/fsync` before success; and `prev_event_hash` always references `event_hash`, not `record_checksum`.

- [ ] **Step 5: Implement `Ledger` with one writer lock and no implicit repair**

```python
@dataclass(frozen=True)
class RecoveryResult:
    events: Sequence[Event]
    quarantined_tail: bytes

class Ledger:
    def __init__(self, path: Path, ledger_id: str):
        self.path, self.ledger_id = path, ledger_id

    def append(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        with self.path.open("a+b") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            fh.seek(0)
            current = self._recover_bytes(fh.read())
            if current.quarantined_tail:
                raise IntegrityError("ledger has an unresolved torn tail")
            expected_seq = len(current.events)
            expected_prev = ZERO_HASH if expected_seq == 0 else current.events[-1].event_hash
            if event.ledger_id != self.ledger_id:
                raise IntegrityError("ledger_id mismatch")
            if event.event_seq != expected_seq or event.prev_event_hash != expected_prev:
                raise IntegrityError("event sequence or prev hash mismatch")
            fh.seek(0, os.SEEK_END)
            fh.write(event.to_line())
            fh.flush()
            os.fsync(fh.fileno())
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        if not existed:
            dfd = os.open(self.path.parent, os.O_RDONLY)
            try: os.fsync(dfd)
            finally: os.close(dfd)

    def recover(self) -> RecoveryResult:
        if not self.path.exists():
            return RecoveryResult((), b"")
        return self._recover_bytes(self.path.read_bytes())

    def _recover_bytes(self, data: bytes) -> RecoveryResult:
        lines = data.splitlines(keepends=True)
        events: list[Event] = []
        for index, line in enumerate(lines):
            is_last = index == len(lines) - 1
            if not line.endswith(b"\n"):
                if is_last: return RecoveryResult(tuple(events), line)
                raise IntegrityError("non-final torn record")
            try:
                event = Event.from_line(line)
            except IntegrityError:
                if is_last: return RecoveryResult(tuple(events), line)
                raise
            expected_prev = ZERO_HASH if index == 0 else events[-1].event_hash
            if event.ledger_id != self.ledger_id or event.event_seq != index:
                raise IntegrityError("ledger identity or sequence mismatch")
            if event.prev_event_hash != expected_prev:
                raise IntegrityError("prev hash mismatch")
            events.append(event)
        return RecoveryResult(tuple(events), b"")
```

Use imports `fcntl`, `os`, `Path`, `Sequence`, `dataclass`, `Event`, `ZERO_HASH`, and `IntegrityError`. Add a quarantine writer that durably stores `quarantined_tail` before a repair command may truncate it; ordinary `recover` remains read-only and no retry loop may append a second business event.

- [ ] **Step 6: Run the ledger suite**

Run: `python3 -m unittest tests.v2.test_event_vectors tests.v2.test_ledger_recovery -v`

Expected: all vector, framing, corruption, and idempotent-recovery cases PASS.

- [ ] **Step 7: Commit canonical storage**

```bash
git add skills/vivarium/vivarium_v2/canonical.py skills/vivarium/vivarium_v2/events.py skills/vivarium/vivarium_v2/ledger.py tests/v2
git commit -m "feat: add canonical event ledgers"
```

### Task 3: Implement the reducer stack and federated certificates

**Files:**
- Create: `skills/vivarium/vivarium_v2/state.py`
- Create: `skills/vivarium/vivarium_v2/schemas/state_machine.yaml`
- Create: `skills/vivarium/vivarium_v2/reducers.py`
- Create: `tests/v2/test_state_machine.py`
- Create: `tests/v2/test_federated_recovery.py`
- Create: `tests/v2/test_run_validity.py`

**Interfaces:**
- Consumes: immutable `Event` tuples and verified ledger prefixes.
- Produces: `RunLocalState`, `ProjectSemanticCut`, `ProjectValidity`, `RunValiditySlice`, `FederatedState`, and their domain-separated roots.

- [ ] **Step 1: Write model tests for the three critical traces**

```python
def test_project_commit_overlays_unchanged_run_tail(self):
    local = reduce_run(self.prepared_run_events)
    before = federate(local, self.project_before_commit)
    after = federate(local, self.project_after_commit)
    self.assertEqual(before.analysis_state, AnalysisState.COMMITTING)
    self.assertEqual(after.analysis_state, AnalysisState.COMMITTED)
    self.assertEqual(before.run_local_state_root, after.run_local_state_root)
    self.assertNotEqual(before.federated_state_root, after.federated_state_root)

def test_fact_change_stales_only_dependent_run(self):
    self.assertEqual(self.slice_for("depends-A", self.cut_A2).state, AnalysisState.STALE_CONTEXT)
    self.assertEqual(self.slice_for("depends-B", self.cut_A2).state, AnalysisState.COMMITTED)

def test_inboxed_observation_blocks_before_opened(self):
    state = reduce_run(self.committed_plus_inboxed)
    self.assertTrue(state.postcommit_intake_blockers)
    self.assertFalse(federate(state, self.project_without_opened).default_retrievable)
```

- [ ] **Step 2: Run reducer tests to verify RED**

Run: `python3 -m unittest tests.v2.test_state_machine tests.v2.test_federated_recovery tests.v2.test_run_validity -v`

Expected: import failure for `state`/`reducers`.

- [ ] **Step 3: Define closed enums and the abort map**

```python
STATE_MACHINE_PATH = Path(__file__).parent / "schemas" / "state_machine.yaml"

def load_state_machine() -> dict[str, object]:
    body = json.loads(STATE_MACHINE_PATH.read_text(encoding="utf-8"))
    if body["schema_version"] != "vivarium.state-machine/v1":
        raise IntegrityError("unsupported state-machine schema")
    return body

STATE_MACHINE = load_state_machine()
AnalysisState = Enum(
    "AnalysisState",
    {value: value for value in STATE_MACHINE["enums"]["analysis_state"]},
    type=str,
)

COMMIT_ABORT_REASON_TARGET = {
    "BRANCH_HEAD_OR_GENERATION_MISMATCH": AnalysisState.STALE_BRANCH,
    "KNOWLEDGE_DEPENDENCY_OR_POLICY_STALE": AnalysisState.STALE_CONTEXT,
    "STAGE_SPEC_OR_ACCEPTANCE_CONTRACT_STALE": AnalysisState.STALE_CONTEXT,
    "EVIDENCE_BUNDLE_INTEGRITY_FAILURE": AnalysisState.BLOCKED,
    "EVIDENCE_CONTRACT_BINDING_STALE": AnalysisState.STALE_CONTEXT,
    "VALIDATOR_REPORT_INVALID": AnalysisState.VALIDATING,
    "CHECKER_REVIEW_OR_QUORUM_INVALID": AnalysisState.CHECK_PENDING,
    "COMPLETION_FAILURE_RETRYABLE": AnalysisState.RETRYABLE_FAILURE,
    "COMPLETION_FAILURE_RESOURCE": AnalysisState.RESOURCE_FAILURE,
    "COMPLETION_FAILURE_PERMANENT": AnalysisState.BLOCKED,
    "COMPLETION_PREEMPTED": AnalysisState.PREEMPTED,
    "COMPLETION_CANCELLED": AnalysisState.CANCELLED,
    "COMPLETION_UNKNOWN_FINALITY": AnalysisState.UNKNOWN_TERMINAL,
    "BUDGET_EXHAUSTED": AnalysisState.BLOCKED,
    "HUMAN_JUDGMENT_REQUIRED": AnalysisState.ESCALATED,
}
```

Write the reviewed closed enums, transitions, and abort cross-product to `schemas/state_machine.yaml` as strict JSON syntax so the standard-library `json` parser can load it. `state.py` compiles that file into concrete tuples at import/build time and asserts every from/to belongs to its reducer namespace; generated tuples may not contain `any`, `same`, `prior`, `*`, or map aliases.

- [ ] **Step 4: Implement pure reducers in the reviewed merge order**

Implement these exact callable interfaces with frozen dataclass outputs and no file I/O:

```python
ReduceRun = Callable[[Sequence[Event]], RunLocalState]
ReduceProjectCut = Callable[[ProjectPrefixes], ProjectSemanticCut]
ReduceProjectValidity = Callable[[ProjectSemanticCut], ProjectValidity]
ReduceRunValidity = Callable[
    [ProjectSemanticCut, ProjectValidity, RunLocalState], RunValiditySlice
]
Federate = Callable[
    [RunLocalState, ProjectSemanticCut, ProjectValidity, RunValiditySlice], FederatedState
]
```

Each root function must hash a fixed dataclass-to-dict projection. `RunValiditySlice` hashes the relevant project subset, not the whole project cut; `FederatedState` separately binds the whole cut root.

- [ ] **Step 5: Add property-style transition enumeration**

Generate every concrete `(from,event,guard,to)` tuple from the closed maps. Assert there is one matching transition for every legal trace, zero for every unlisted trace, no alias remains, and an invalid event leaves all reducer roots unchanged.

- [ ] **Step 6: Run reducer tests**

Run: `python3 -m unittest tests.v2.test_state_machine tests.v2.test_federated_recovery tests.v2.test_run_validity -v`

Expected: all commit/recheck, correction, unrelated-change, inbox-blocker, abort-map, and replay tests PASS.

- [ ] **Step 7: Commit reducers**

```bash
git add skills/vivarium/vivarium_v2/state.py skills/vivarium/vivarium_v2/reducers.py tests/v2
git commit -m "feat: add federated state reducers"
```

### Task 4: Add project transactions, recovery, rollback, and fork

**Files:**
- Create: `skills/vivarium/vivarium_v2/project.py`
- Create: `tests/v2/test_project_init.py`
- Create: `tests/v2/test_commit_transaction.py`
- Create: `tests/v2/test_rollback_fork.py`
- Create: `tests/v2/test_postcommit_inbox.py`
- Create: `tests/v2/support.py`

**Interfaces:**
- Consumes: Task 2 ledgers and Task 3 reducers.
- Produces: `ProjectStore.init`, `register_run`, `prepare_commit`, `complete_commit`, `abort_commit`, `inbox_observation`, `open_recheck`, `recover`, `rollback`, and `fork`.

`tests/v2/support.py` exports `FrozenClock`, `fixture_store_at_revision`, `valid_prepared_commit`, `prepared_fixture`, `inject_once`, and the exact `COMMIT_CRASH_POINTS` tuple used below. Each helper creates a fresh temporary project through public APIs; it never edits ledger bytes except the fault injector at its named boundary.

- [ ] **Step 1: Write the five-ledger bootstrap and revision tests**

Assert five genesis events contain no `project_revision`, the derived empty revision is 0, five interleaved semantic events receive 1..5, `HANDOFF_PUBLISHED` receives no new revision, and a commit starting at 17 records 18.

```python
class ProjectRevisionTests(unittest.TestCase):
    def test_bootstrap_and_global_revision(self):
        store = ProjectStore.init(self.root, FrozenClock("2026-07-18T00:00:00Z"))
        cut = store.capture()[0]
        self.assertEqual(cut.project_revision, 0)
        self.assertTrue(all("project_revision" not in event.payload
                            for event in store.genesis_events()))
        observed = [store.append_fixture_event(name).payload["project_revision"]
                    for name in ("truth", "decision", "work", "memory", "run-registry")]
        self.assertEqual(observed, [1, 2, 3, 4, 5])

    def test_commit_consumes_next_revision(self):
        store = fixture_store_at_revision(self.root, 17)
        event = store.complete_commit(valid_prepared_commit(store))
        self.assertEqual(event.payload["project_revision"], 18)
```

- [ ] **Step 2: Write commit crash-window tests**

Cover artifact write, artifact fsync, prepare fsync, project complete-cut fsync, projection replacement, every abort reason, and 100 repeated recoveries. Counters must show one `STAGE_COMMITTED` or one `STAGE_COMMIT_ABORTED`, never both.

```python
class CommitCrashTests(unittest.TestCase):
    def test_each_crash_window_converges_once(self):
        for point in COMMIT_CRASH_POINTS:
            with self.subTest(point=point):
                store = prepared_fixture(self.root / point)
                inject_once(store, point)
                roots = [store.recover().federated_state_root for _ in range(100)]
                self.assertEqual(len(set(roots)), 1)
                types = store.business_event_types()
                self.assertLessEqual(types.count("STAGE_COMMITTED"), 1)
                self.assertLessEqual(types.count("STAGE_COMMIT_ABORTED"), 1)
                self.assertFalse({"STAGE_COMMITTED", "STAGE_COMMIT_ABORTED"}.issubset(types))
```

- [ ] **Step 3: Implement project layout and bootstrap**

```python
PROJECT_LEDGERS = (
    ("truth", "TRUTH_LEDGER_GENESIS"),
    ("decision", "DECISION_LEDGER_GENESIS"),
    ("work", "WORK_LEDGER_GENESIS"),
    ("memory", "MEMORY_LEDGER_GENESIS"),
    ("run-registry", "RUN_REGISTRY_LEDGER_GENESIS"),
)

@dataclass
class ProjectStore:
    root: Path

ProjectStoreInit = Callable[[Path, Clock], ProjectStore]
ProjectCapture = Callable[[ProjectStore], tuple[ProjectSemanticCut, Sequence[RunLocalState]]]
```

Create ledgers, locks, quarantine, artifact directories, and projections with temp-file + file fsync + rename + directory fsync. Initialization refuses a partial existing project and never overwrites it.

- [ ] **Step 4: Implement two-ledger commit and abort transactions**

Acquire locks in the reviewed global order. `complete_commit` must validate the prepare event/hash, branch/work CAS, dependency vector, policy, completion proof, validator seal, Checker quorum, and budget before appending the project complete-cut. `abort_commit` must validate the closed reason map and atomically set preparation inactive plus the mapped state.

- [ ] **Step 5: Implement durable post-commit intake**

`inbox_observation` writes bounded canonical raw bytes directly in one `POSTCOMMIT_OBSERVATION_INBOXED` run event while holding project/branch/run/work locks. `recover` enumerates inbox-minus-open and open-minus-close before serving any active result. Oversize input writes a typed truncation blocker and returns `ESCALATED`; it never produces a success proof.

- [ ] **Step 6: Implement append-only rollback and fork**

Rollback appends invalidated roots and a new branch head; fork creates a new immutable branch ID with parent checkpoint/spec delta. Neither operation deletes events or artifacts. A late old-branch commit must fail its generation/head CAS.

- [ ] **Step 7: Run project fault tests**

Run: `python3 -m unittest tests.v2.test_project_init tests.v2.test_commit_transaction tests.v2.test_postcommit_inbox tests.v2.test_rollback_fork -v`

Expected: all crash points converge to one byte-identical state; external invocation counters remain zero.

- [ ] **Step 8: Commit project transactions**

```bash
git add skills/vivarium/vivarium_v2/project.py tests/v2
git commit -m "feat: add project transactions and recovery"
```

### Task 5: Add supervised agent-only and local execution

**Files:**
- Create: `skills/vivarium/vivarium_v2/execution.py`
- Create: `tests/v2/test_agent_only_completion.py`
- Create: `tests/v2/test_local_execution.py`
- Create: `tests/v2/test_completion_classifier.py`
- Modify: `tests/v2/support.py`

**Interfaces:**
- Consumes: registered runs, run ledger, content objects, and reducer states.
- Produces: `ExecutionIntent`, `ProcessReceipt`, `ExecutionEvidenceCut`, `CompletionClassification`, success-only `CompletionProof`, `LocalExecutionBroker.run_or_recover`, `classify_completion`, and `build_completion_proof`.

- [ ] **Step 1: Write at-most-once and completion tests**

Inject crashes before intent fsync, after intent/before wrapper start, after receipt/before attach, after child spawn, after wrapper exit/before quiescence, and after Classification/before Proof. Assert `external_main_start_count <= 1`, PID/boot/start identity is checked, all descendants are reaped, nonzero/signal/OOM never creates a success proof, and only a durable success classification plus policy-allowed proof enters `VALIDATING`.

```python
class LocalExecutionTests(unittest.TestCase):
    def test_crash_windows_never_start_twice(self):
        for point in LOCAL_CRASH_POINTS:
            with self.subTest(point=point):
                harness = FakeLocalHarness(crash_at=point)
                broker = LocalExecutionBroker(harness=harness, store=self.store)
                broker.run_or_recover(self.intent)
                for _ in range(100): broker.recover(self.intent.execution_intent_id)
                self.assertLessEqual(harness.main_start_count, 1)

    def test_oom_cannot_construct_success_proof(self):
        cut = fixture_evidence_cut(exit_code=137, oom=True, sentinel=True)
        classification = classify_completion(cut)
        self.assertEqual(classification.outcome, "failure_resource")
        with self.assertRaises(PolicyError):
            build_completion_proof(classification, cut)
```

Define `LOCAL_CRASH_POINTS`, `FakeLocalHarness`, and `fixture_evidence_cut` in `tests/v2/support.py`; the fake exposes boot/PID/start/process-group identity and descendant/reap counters.

- [ ] **Step 2: Define the fixed execution records**

```python
@dataclass(frozen=True)
class ExecutionIntent:
    execution_intent_id: str
    run_id: str
    stage_id: str
    attempt_id: str
    execution_mode: str
    argv: Sequence[str]
    cwd_digest: str
    environment_digest: str
    execution_request_key: str

@dataclass(frozen=True)
class ProcessReceipt:
    execution_intent_id: str
    boot_id: str
    pid: int
    process_group_id: int
    process_start_identity: str
    stdout_digest: str
    stderr_digest: str

@dataclass(frozen=True)
class CompletionClassification:
    outcome: str
    authority: str
    evidence_cut_digest: str
    absence_evidence_digest: str
```

Conditional fields use explicit canonical empty roots rather than omitted values. `CompletionProof` constructor accepts only `outcome="success"`; every other outcome is represented only by `CompletionClassification`.

- [ ] **Step 3: Implement agent-only harness completion**

Agent-only policy forbids process, network, broker, and scheduler capabilities. Success requires Maker terminal status, child set empty, capability revocation receipt, sealed output bundle, and quiescence. Any requested/observed external capability yields a durable failure classification and commit count zero.

- [ ] **Step 4: Implement the local wrapper and attach-only recovery**

Persist `LOCAL_EXECUTION_INTENT_RECORDED` before starting the wrapper. The wrapper writes and fsyncs `ProcessReceipt` before `exec`; recovery with a matching boot/PID/start/process-group attaches, while missing or mismatched identity enters `LOCAL_EXECUTION_UNCERTAIN` and never starts a second main process. Capture Broker-owned stdout/stderr and descendant/lease/quiescence receipts.

- [ ] **Step 5: Implement completion classification and proof durability**

Classify success, retryable/resource/permanent failure, preemption, cancellation, and unknown finality from the frozen evidence cut. Write canonical classification/proof objects with file and directory fsync before the state-changing event. A sentinel cannot override supervisor/OOM/signal failure.

- [ ] **Step 6: Run execution tests**

Run: `python3 -m unittest tests.v2.test_agent_only_completion tests.v2.test_local_execution tests.v2.test_completion_classifier -v`

Expected: all crash windows are idempotent, success proof count is exact, and no uncertain execution restarts.

- [ ] **Step 7: Commit execution supervision**

```bash
git add skills/vivarium/vivarium_v2/execution.py tests/v2
git commit -m "feat: add supervised local execution"
```

### Task 6: Add immutable evidence and Maker/Checker separation

**Files:**
- Create: `skills/vivarium/vivarium_v2/evidence.py`
- Create: `skills/vivarium/vivarium_v2/roles.py`
- Create: `tests/v2/test_evidence_sealing.py`
- Create: `tests/v2/test_role_isolation.py`
- Create: `tests/v2/test_checker_quorum.py`
- Modify: `tests/v2/support.py`

**Interfaces:**
- Consumes: project store and content hashing.
- Produces: `EvidenceBundle`, `ValidatorSeal`, `CheckerAssignment`, `CheckerReview`, `CapabilityReceipt`, `GateDecision`, and `decide_gate`.

- [ ] **Step 1: Write negative capability and sealing tests**

Attempt symlink/hardlink/FIFO/path escape inputs, Maker writes to canonical ledgers, Checker writes candidate files, a live Validator report seal, two reviews from one namespace, stale evidence bindings, and a soft-isolation auto commit. Every case must fail before commit.

```python
class RoleIsolationTests(unittest.TestCase):
    def test_soft_isolation_never_commits(self):
        decision = decide_gate(
            hard_pass=True,
            reviews=(valid_review("a"), valid_review("b")),
            policy=QuorumPolicy(required=2),
            receipts=(receipt("a", "same-uid"), receipt("b", "same-uid")),
            isolation_grade="soft_isolation",
        )
        self.assertFalse(decision.may_commit)

    def test_snapshotter_rejects_non_regular_inputs(self):
        for attack in (make_symlink, make_hardlink, make_fifo, make_escape_path):
            with self.subTest(attack=attack.__name__), self.assertRaises(IntegrityError):
                snapshot_candidate(attack(self.workspace), self.store)
```

Add `valid_review`, `receipt`, and the four filesystem attack constructors to `tests/v2/support.py`. Each constructor operates only inside its fresh temporary fixture directory.

- [ ] **Step 2: Define the role contracts**

```python
@dataclass(frozen=True)
class CapabilityReceipt:
    assignment_id: str
    namespace_id: str
    allowed_read_roots: Sequence[str]
    allowed_write_roots: Sequence[str]
    process_allowed: bool
    network_allowed: bool
    revoked: bool
    digest: str

@dataclass(frozen=True)
class GateDecision:
    hard_validators_pass: bool
    checker_quorum_pass: bool
    isolation_grade: str
    may_commit: bool

@dataclass(frozen=True)
class CheckerReview:
    assignment_id: str
    namespace_id: str
    verdict: str
    severities: Sequence[str]
    binding_digest: str

@dataclass(frozen=True)
class QuorumPolicy:
    required: int
    binding_digest: str

def decide_gate(hard_pass: bool, reviews: Sequence[CheckerReview],
                policy: QuorumPolicy, receipts: Sequence[CapabilityReceipt],
                isolation_grade: str) -> GateDecision:
    receipt_by_assignment = {item.assignment_id: item for item in receipts}
    valid = [
        review for review in reviews
        if review.assignment_id in receipt_by_assignment
        and receipt_by_assignment[review.assignment_id].revoked
        and review.namespace_id == receipt_by_assignment[review.assignment_id].namespace_id
        and review.binding_digest == policy.binding_digest
        and review.verdict == "PASS"
        and not ({"Critical", "Major"} & set(review.severities))
    ]
    namespaces = {review.namespace_id for review in valid}
    quorum = len(valid) >= policy.required and len(namespaces) >= policy.required
    may_commit = hard_pass and quorum and isolation_grade == "hard_isolation"
    return GateDecision(hard_pass, quorum, isolation_grade, may_commit)
```

`decide_gate` returns `may_commit=False` for any hard failure, live capability, duplicate namespace, evidence/rubric mismatch, Critical/Major finding, or `soft_isolation`.

- [ ] **Step 3: Implement no-follow evidence snapshotting**

Traverse with directory file descriptors and `follow_symlinks=False`; accept regular files with link count 1 only. Build sorted payload/log manifests, fsync objects, revoke writers, and then seal validator/review bodies. The Maker never supplies authoritative root fields.

- [ ] **Step 4: Implement blind Checker packets and quorum**

Checker context contains mission, rubric, acceptance contract, sealed evidence pair, and validator seal; it excludes Maker chat/self-score. L2 requires two different assignment IDs and attested namespaces. A minority Critical finding always escalates.

- [ ] **Step 5: Run isolation and quorum tests**

Run: `python3 -m unittest tests.v2.test_evidence_sealing tests.v2.test_role_isolation tests.v2.test_checker_quorum -v`

Expected: all attacks fail; one valid L1 review passes only under hard isolation; valid L2 requires two namespaces.

- [ ] **Step 6: Commit role gates**

```bash
git add skills/vivarium/vivarium_v2/evidence.py skills/vivarium/vivarium_v2/roles.py tests/v2
git commit -m "feat: separate maker checker and evidence gates"
```

### Task 7: Implement facts, memory sealing, and bounded handoff

**Files:**
- Create: `skills/vivarium/vivarium_v2/knowledge.py`
- Create: `skills/vivarium/vivarium_v2/handoff.py`
- Create: `tests/v2/test_fact_correction.py`
- Create: `tests/v2/test_memory_lifecycle.py`
- Create: `tests/v2/test_handoff_snapshot.py`
- Modify: `tests/v2/support.py`

**Interfaces:**
- Consumes: ProjectStore captures, reducers, and sealed evidence.
- Produces: `change_fact_head`, `promote_procedure`, `withdraw_memory`, `compile_context`, `build_handoff_snapshot`, and `render_handoff`.

- [ ] **Step 1: Write memory-drift tests**

Create fact A=1, a procedural memory P depending on A, a committed result depending on P, then correct A=2. Default retrieval repeated 1,000 times must never return A=1 or P; audit mode returns them with sealed status and the new head. An unrelated fact B change must not stale the A-only attempt.

```python
class MemoryDriftTests(unittest.TestCase):
    def test_correction_seals_old_fact_and_procedure(self):
        project = knowledge_fixture(fact_value="1", procedure_id="P")
        project.change_fact_head("A", "2", reason="corrected source")
        for _ in range(1000):
            ids = {item.stable_id for item in project.retrieve("A", audit_mode=False)}
            self.assertNotIn("fact-A-v1", ids)
            self.assertNotIn("P", ids)
        audit = project.retrieve("A", audit_mode=True)
        self.assertTrue(all(item.status == "NON_ACTIVE_HISTORY" for item in audit
                            if item.stable_id in {"fact-A-v1", "P"}))

    def test_procedure_promotion_requires_evidence_and_regression(self):
        candidate = procedure_candidate(source_episode_ids=("e1", "e2"), scope="ani/v1")
        with self.assertRaises(PolicyError):
            promote_procedure(candidate, validator_pass=True, checker_pass=True,
                              regression_pass=False)
```

- [ ] **Step 2: Write HandoffSnapshot race tests**

Capture three runs, including cancellation and accounting debt. Inject fact correction, memory withdrawal, run append, commit, and rollback at every capture boundary. A published snapshot must be a single reconstructable cut, contain all registered runs, fit the byte budget, and exclude stale active success.

```python
class HandoffRaceTests(unittest.TestCase):
    def test_every_published_snapshot_replays(self):
        for mutation in HANDOFF_RACE_MUTATIONS:
            with self.subTest(mutation=mutation):
                project = three_run_project_fixture()
                published = race_capture_and_mutation(project, mutation)
                replayed = project.replay_snapshot(published.snapshot_id)
                self.assertEqual(published, replayed)
                self.assertEqual(len(published.run_ledger_tails), 3)
                self.assertLessEqual(len(render_handoff(published)), 16_384)
```

Add the fixture builders and `HANDOFF_RACE_MUTATIONS` to `tests/v2/support.py`; the race helper returns only after the publisher either wins a complete CAS or discards and recaptures.

- [ ] **Step 3: Implement fact/memory events and retrieval**

All head/status changes append old/new head, project revision, canonical dependency edges, scanned cut, and invalidation roots in one event. Default retrieval applies `active && is_head && source_valid && dependency_current && not_sealed`; audit retrieval marks `NON_ACTIVE_HISTORY`.

Memory Curator may append raw episodes automatically, but a procedural promotion requires at least one source episode set, a fixed scope, deterministic regression PASS, independent Checker PASS, no conflict with active fact/policy heads, and a new immutable memory head. Scientific propositions route through `FACT_HEAD_CHANGED`; semantic memory stores only an index to active fact IDs/digests. Withdrawal uses the same atomic invalidation path as fact correction.

- [ ] **Step 4: Implement deterministic HandoffSnapshot**

Use the exact reviewed fields, sorted run certificates, and domain-separated root formulas. Renderer sorting is `(priority, entity_type, canonical_key, stable_id)`, byte limit is 16,384, mandatory records are never truncated, and overflow uses `OVERFLOW count=<n> index=<digest-ref>`.

- [ ] **Step 5: Keep handoff a pure projection**

`HANDOFF_PUBLISHED` stores only snapshot/content/renderer/publisher receipt fields and never `activated_objects` or edges. Two publications of one snapshot keep all semantic roots unchanged; `current.md` is replaced atomically and rebuilt if its receipt cut is stale.

- [ ] **Step 6: Run knowledge and handoff tests**

Run: `python3 -m unittest tests.v2.test_fact_correction tests.v2.test_memory_lifecycle tests.v2.test_handoff_snapshot -v`

Expected: all drift, sealing, multi-run, overflow, and torn-projection cases PASS.

- [ ] **Step 7: Commit knowledge management**

```bash
git add skills/vivarium/vivarium_v2/knowledge.py skills/vivarium/vivarium_v2/handoff.py tests/v2
git commit -m "feat: add drift resistant project knowledge"
```

### Task 8: Add bioinformatics contracts and deterministic validators

**Files:**
- Create: `skills/vivarium/vivarium_v2/bio/__init__.py`
- Create: `skills/vivarium/vivarium_v2/bio/contracts.py`
- Create: `skills/vivarium/vivarium_v2/bio/validators.py`
- Create: `tests/v2/fixtures/bio/`
- Create: `tests/v2/test_bio_artifacts.py`
- Create: `tests/v2/test_statistics_contract.py`
- Create: `tests/v2/test_database_identity.py`
- Modify: `tests/v2/support.py`

**Interfaces:**
- Consumes: stage contracts, immutable input manifests, and candidate evidence.
- Produces: typed contracts, `validate_contract`, `validate_family_results`, and `ValidationFinding` records with exact artifact spans.

- [ ] **Step 1: Write fixture-first hard-gate tests**

Fixtures must cover duplicate sample IDs, FASTA ID normalization collisions, CRLF versus LF canonicalization, mixed genetic codes, multi-contig coordinate frames, interval off-by-one, missing ANI pairs, alignment/tree taxa mismatch, truncated compressed data, top-10-only p-values from a 100-member family, weak database identity cache lookup, and a mechanism claim supported only by computation.

```python
class BioHardGateTests(unittest.TestCase):
    def test_bad_fixtures_have_stable_signatures(self):
        expected = {
            "duplicate_samples": "BIO_SAMPLE_ID_DUPLICATE",
            "mixed_code_wrong_translation": "BIO_GENETIC_CODE_MISMATCH",
            "coordinate_off_by_one": "BIO_COORDINATE_ROUNDTRIP_FAIL",
            "ani_missing_pair": "BIO_MATRIX_PAIR_MISSING",
            "tree_taxa_mismatch": "BIO_TREE_ALIGNMENT_TAXA_MISMATCH",
        }
        for fixture, signature in expected.items():
            with self.subTest(fixture=fixture):
                findings = validate_contract(load_bio_fixture(fixture))
                self.assertIn(signature, {item.signature for item in findings if item.hard_fail})

    def test_truncated_hypothesis_results_fail_coverage(self):
        family = family_fixture(member_count=100)
        results = result_fixture(member_ids=family.member_ids[:10])
        self.assertEqual(validate_family_results(family, results).signature,
                         "STAT_FAMILY_COVERAGE_MISMATCH")
```

- [ ] **Step 2: Define typed contracts**

```python
@dataclass(frozen=True)
class CoordinateFrame:
    reference_digest: str
    contig_id: str
    origin: int
    interval: str
    strand: str
    circular: bool

@dataclass(frozen=True)
class HypothesisFamily:
    family_id: str
    member_manifest_root: str
    stable_id_schema_digest: str
    expected_member_count: int
    prefilter_covariate_root: str

@dataclass(frozen=True)
class DatabaseIdentity:
    asset_id: str
    release: str
    content_manifest_root: str
    identity_strength: str
    weak_reason: str
    cache_eligible: bool
```

Schemas reject extra fields, implicit defaults, floats for exact scientific decimals, unknown coordinate conventions, and `weak + cache_eligible=true`.

- [ ] **Step 3: Implement identity and structural validators**

Implement sample bijection, typed sequence alphabet, stable-ID collision checks, record counts, file magic, compressed stream completion, index pairing, coordinate round-trip, genetic-code translation round-trip, and workflow seam identity checks.

- [ ] **Step 4: Implement statistical family validation**

Canonical family JSONL uses one JCS object plus LF per stable ID. Result coverage requires exactly one `tested`, `filtered_by_preregistered_rule`, or `failed` record per member. Recompute the eligible set and BH adjustment from raw p-values; never trust adjusted values from a truncated tool output.

- [ ] **Step 5: Implement database identity cache policy**

Strong identity requires a verified manifest over every consumed shard/index. Weak identity returns `cache_eligible=False`, cache lookup count zero, and blocks L2/L3 automatic commit. A changed shard under the same release/path changes a strong root and stage key.

- [ ] **Step 6: Run bioinformatics validator tests**

Run: `python3 -m unittest tests.v2.test_bio_artifacts tests.v2.test_statistics_contract tests.v2.test_database_identity -v`

Expected: every bad fixture yields a stable hard-fail signature; every paired positive fixture passes.

- [ ] **Step 7: Commit bioinformatics contracts**

```bash
git add skills/vivarium/vivarium_v2/bio tests/v2
git commit -m "feat: add bioinformatics contract validators"
```

### Task 9: Add Phase A cluster static profiles and fake scheduler

**Files:**
- Create: `skills/vivarium/vivarium_v2/cluster/__init__.py`
- Create: `skills/vivarium/vivarium_v2/cluster/profiles.py`
- Create: `skills/vivarium/vivarium_v2/cluster/arrays.py`
- Create: `skills/vivarium/vivarium_v2/cluster/static.py`
- Create: `skills/vivarium/vivarium_v2/cluster/fake.py`
- Create: `tests/v2/test_cluster_static.py`
- Create: `tests/v2/test_cluster_render.py`
- Create: `tests/v2/test_fake_scheduler.py`
- Create: `tests/v2/test_array_identity.py`
- Modify: `tests/v2/support.py`

**Interfaces:**
- Consumes: normalized resource requests and an explicit profile file.
- Produces: `StaticFingerprint`, `fingerprint_executable`, `lint_profile`, `render_submission`, array-root functions, fake receipts, and hard-disabled `submit_live`. No real mutation interface is active.

- [ ] **Step 1: Write a malicious executable fixture**

Create a fake `qsub` file whose body would append to a sentinel if executed. Static detect, lint, fingerprint, and render must leave the sentinel absent. Also patch `subprocess.run/Popen` to fail the test if cluster static code calls either function.

```python
class StaticClusterTests(unittest.TestCase):
    def test_detection_never_executes_scheduler_binary(self):
        qsub, sentinel = make_mutating_qsub_fixture(self.root)
        with mock.patch("subprocess.run", side_effect=AssertionError("execution forbidden")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("execution forbidden")):
            fingerprint = fingerprint_executable(qsub)
            lint_profile(profile_fixture(submit_path=qsub), fingerprint)
            render_submission(profile_fixture(submit_path=qsub), request_fixture())
        self.assertFalse(sentinel.exists())

    def test_live_interface_is_disabled(self):
        with self.assertRaises(LiveClusterDisabled):
            submit_live(profile_fixture(), request_fixture())
```

`make_mutating_qsub_fixture`, `profile_fixture`, and `request_fixture` belong in `tests/v2/support.py`; the executable fixture is never invoked by test setup.

- [ ] **Step 2: Define profiles and the hard-disabled live interface**

```python
@dataclass(frozen=True)
class ClusterProfile:
    profile_id: str
    scheduler: str  # qsub-sge, qsub-pbs, or csub
    submit_path: str
    resource_semantics: str
    live_mutation_enabled: bool = False

class LiveClusterDisabled(PolicyError):
    exit_code = 4

def submit_live(*_args, **_kwargs):
    raise LiveClusterDisabled("Phase A live cluster mutation is disabled")
```

- [ ] **Step 3: Implement static fingerprinting without execution**

Open the executable with no-follow semantics, require a regular file, hash bytes, record device/inode/mode/size/mtime, and hash companion paths/profile bytes. Do not call any executable for version/help detection. Lint rejects mutable path/fingerprint mismatches.

- [ ] **Step 4: Implement deterministic qsub/csub rendering**

Render from normalized resources and profile semantics only. Include project/run/branch/stage/attempt/request tags, sentinel paths, array manifest/binding roots, and no shell interpolation of untrusted sample IDs. Golden tests cover SGE per-slot memory, PBS select/ncpus/mem, and csub templates.

- [ ] **Step 5: Implement fake scheduler state and counters**

The fake adapter exposes submit/cancel/hold/release/status/accounting counters, receipt-loss injection, HELD/Eqw/OOM/timeout states, and one-wire-attempt enforcement. It is the only mutation-capable adapter in Phase A.

- [ ] **Step 6: Implement array identities and retry lineage**

Canonicalize the immutable task manifest, native-index binding, per-task key, and gather root with the reviewed domain separators and JCS/LF rules. Hard-code expected roots `sha256:890f05b124b2ec97319f6be34399d113be61415662970e8dc3f18cae6f6b0c54`, `sha256:d9a039247f4e7298772c5d7c5cd2c08f5bb3eac7dbab6105236d5ea1c54e68d9`, and `sha256:31c594ee6df57b900cffc9c16153ecee15295998bad1b0d9540a8eab1c8c804c`. A retry of failed task 4 creates a new parent intent containing only task 4 and preserves the other nine task attempts byte-for-byte.

- [ ] **Step 7: Run cluster Phase A tests**

Run: `python3 -m unittest tests.v2.test_cluster_static tests.v2.test_cluster_render tests.v2.test_fake_scheduler tests.v2.test_array_identity -v`

Expected: malicious executable sentinel absent; real mutation methods always raise; fake scheduler crash/recovery invocation count remains one.

- [ ] **Step 8: Commit cluster static support**

```bash
git add skills/vivarium/vivarium_v2/cluster tests/v2
git commit -m "feat: add static cluster profiles and fake scheduler"
```

### Task 10: Integrate the V2 CLI and migrate without overwriting legacy runs

**Files:**
- Modify: `skills/vivarium/vivarium_v2/cli.py`
- Modify: `skills/vivarium/scripts/orchestrate.py`
- Create: `tests/v2/test_cli_end_to_end.py`
- Create: `tests/v2/test_legacy_import.py`
- Modify: `tests/v2/support.py`
- Modify: `skills/vivarium/SKILL.md`
- Modify: `README.md`
- Modify: `README.en.md`

**Interfaces:**
- Consumes: Tasks 2-9 public APIs.
- Produces: `v2 init`, `v2 status`, `v2 recover`, `v2 rollback`, `v2 fork`, `v2 handoff`, `v2 validate`, `v2 cluster detect`, `v2 cluster lint`, and `v2 cluster render`.

- [ ] **Step 1: Write end-to-end CLI tests**

Initialize a V2 project, register a run, append a fake completed attempt, seal validation/review, commit, render handoff, recover after deleting projections, rollback, and fork. Assert JSON output, stable exit codes, one active branch head, and zero real scheduler invocations.

```python
class CliEndToEndTests(unittest.TestCase):
    def test_v2_project_commit_recover_rollback_fork(self):
        project = self.root / "project"
        self.assertEqual(run_cli("v2", "init", "--project", str(project)).returncode, 0)
        self.assertEqual(run_cli("v2", "run", "register", "--project", str(project),
                                 "--run", "run-1").returncode, 0)
        commit_fixture_through_public_cli(project, run_id="run-1")
        before = json.loads(run_cli("v2", "status", "--project", str(project)).stdout)
        move_projections_to_fixture_trash(project)
        self.assertEqual(run_cli("v2", "recover", "--project", str(project)).returncode, 0)
        after = json.loads(run_cli("v2", "status", "--project", str(project)).stdout)
        self.assertEqual(before["federated_state_root"], after["federated_state_root"])
        self.assertEqual(run_cli("v2", "rollback", "--project", str(project),
                                 "--checkpoint", "cp-1").returncode, 0)
        self.assertEqual(run_cli("v2", "fork", "--project", str(project),
                                 "--from-checkpoint", "cp-1", "--branch", "branch-2").returncode, 0)
        self.assertEqual(read_real_scheduler_invocations(project), 0)
```

All CLI helpers live in `tests/v2/support.py`. `move_projections_to_fixture_trash` uses the test fixture's recoverable trash directory and never touches canonical ledgers.

- [ ] **Step 2: Implement explicit command routing**

Each command returns structured JSON on stdout and diagnostics on stderr. Mutating commands require project/run identity and refuse unregistered runs. `cluster detect/lint/render` accept explicit profile/executable paths and never invoke them.

- [ ] **Step 3: Implement legacy import as append-only migration**

Import reads `run_manifest.json`, writes a new V2 project/run with provenance pointing to the legacy manifest digest, and leaves the legacy directory byte-identical. Ambiguous `done` stages import as historical evidence requiring fresh validation/checking; they do not become committed automatically.

- [ ] **Step 4: Rewrite the umbrella skill instructions**

Document Maker → immutable evidence → deterministic Validator → blind Checker → complete-cut; fact/memory sealing; rollback/fork; bounded handoff; Phase A static cluster commands; and the explicit Phase B exclusion. Retain sub-skill routing and never instruct the agent to auto-install tools.

- [ ] **Step 5: Run CLI, import, and legacy regression tests**

Run: `python3 -m unittest tests.v2.test_cli_end_to_end tests.v2.test_legacy_import tests.v2.test_legacy_compatibility -v`

Expected: all V2 commands pass, legacy input remains byte-identical, and old CLI output remains compatible.

- [ ] **Step 6: Commit integration and docs**

```bash
git add skills/vivarium/vivarium_v2/cli.py skills/vivarium/scripts/orchestrate.py skills/vivarium/SKILL.md README.md README.en.md tests/v2
git commit -m "feat: integrate vivarium loop engineer cli"
```

### Task 11: Run the complete Phase A gate and produce release evidence

**Files:**
- Create: `tests/v2/test_clean_room.py`
- Create: `tests/v2/test_fault_matrix.py`
- Create: `tests/v2/fixtures/fault_matrix.json`
- Create: `docs/superpowers/reviews/vivarium-v2-phase-a-verification.md`
- Modify: `.claude-plugin/plugin.json`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the complete Phase A implementation.
- Produces: a reproducible verification record and versioned pre-release metadata.

- [ ] **Step 1: Add clean-room dependency tests**

Scan imports, package metadata, install scripts, tests, generated files, and runtime discovery catalogs for `bioSkills`, `GPTomics`, or external copied module identifiers. The design-study links are the only allowed matches and are outside runtime code.

```python
class CleanRoomTests(unittest.TestCase):
    def test_runtime_tree_has_no_external_bio_dependency(self):
        roots = [Path("skills"), Path("tests"), Path("install.sh"),
                 Path(".claude-plugin")]
        forbidden = ("bio" + "skills", "gpt" + "omics")
        matches = []
        for root in roots:
            files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
            for path in files:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                if any(token in text for token in forbidden): matches.append(str(path))
        self.assertEqual(matches, [])
```

- [ ] **Step 2: Add the consolidated fault matrix**

Parameterize the reviewed crash windows: ledger torn tail, prepare/complete-cut, every abort reason, fact/memory correction, concurrent recheck diamond, INBOXED/OPENED/ACCEPTED/close, role capability revocation, weak database identity, hypothesis-family truncation, cluster real-mutation denial, fake receipt loss, and rollback versus late commit.

```python
class FaultMatrixTests(unittest.TestCase):
    def test_all_fault_scenarios_match_machine_oracles(self):
        for scenario in load_fault_scenarios():
            with self.subTest(scenario=scenario.scenario_id):
                observed = execute_fault_scenario(scenario)
                self.assertEqual(observed.event_multiset, scenario.expected_event_multiset)
                self.assertEqual(observed.active_heads, scenario.expected_active_heads)
                self.assertEqual(observed.real_scheduler_invocations, 0)
                self.assertLessEqual(observed.fake_wire_invocations,
                                     scenario.max_fake_wire_invocations)
                self.assertEqual(len(set(observed.recovery_roots)), 1)
```

`load_fault_scenarios` reads a checked-in strict-JSON fixture generated from the reviewed oracle table; `execute_fault_scenario` uses only fake clocks, fake process harnesses, fake scheduler transport, and temporary project directories.

- [ ] **Step 3: Run the full suite twice from clean temporary projects**

Run: `python3 -m unittest discover -s tests/v2 -p 'test_*.py' -v`

Expected: PASS.

Run the same command a second time.

Expected: PASS with identical golden roots, event multisets, and fake external invocation counts.

- [ ] **Step 4: Run mechanical and policy scans**

Run: `python3 -m compileall -q skills/vivarium/vivarium_v2 skills/vivarium/scripts/orchestrate.py`

Expected: exit 0.

Run: `rg -n -i 'bioskills|GPTomics' skills tests install.sh .claude-plugin`

Expected: no output.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Write the verification record**

Record exact commands, Python/platform details, test counts, G1/G2 hashes, array/gather roots, fault-matrix counts, real scheduler invocation count `0`, fake invocation results, and known Phase B exclusions. Do not claim site-qualified cluster support.

- [ ] **Step 6: Bump the plugin pre-release version and changelog**

Use the repository's existing semantic-version format. Describe V2 Phase A as opt-in, legacy-compatible, real-cluster-disabled, and clean-room independent.

- [ ] **Step 7: Request independent code review**

Use `superpowers:requesting-code-review` against the reviewed design and this plan. Any Critical/Major finding reopens the relevant task; do not mark Phase A complete from process evidence alone.

- [ ] **Step 8: Commit release evidence**

```bash
git add tests/v2 docs/superpowers/reviews/vivarium-v2-phase-a-verification.md .claude-plugin/plugin.json CHANGELOG.md
git commit -m "test: verify vivarium v2 phase a"
```

### Task 12: Run a blinded multi-project comparison against no-skill and V1 baselines

**Files:**
- Create: `benchmarks/v2/multi_project/benchmark_manifest.json`
- Create: `benchmarks/v2/multi_project/oracles.json`
- Create: `benchmarks/v2/multi_project/run_benchmark.py`
- Create: `tests/v2/test_benchmark_protocol.py`
- Create: `docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.zh-CN.md`
- Create: `docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.en.md`

**Interfaces:**
- Consumes: read-only manifests from `/Users/gaojian/Desktop/Shewanella_V2_Analysis`, `/Users/gaojian/Desktop/SY280_Cas9_structure`, and `/Users/gaojian/Desktop/抗菌肽模型`; frozen GitHub V1; the completed Phase A V2 skill; and a matched no-Vivarium-skill agent environment.
- Produces: paired, blinded artifacts for `no_skill`, `vivarium_v1_frozen`, and `vivarium_v2_frozen`, plus a detailed Markdown report comparing correctness, evidence integrity, biological overclaim control, drift resistance, rollback/recovery, reproducibility, wall time, and token/tool cost.

- [ ] **Step 1: Freeze a safe benchmark manifest**

Inventory with `stat` and bounded reads only. Classify every candidate as `metadata_only`, `small_content_allowed`, or `large_raw_extract_later`; do not unpack raw archives during inventory. Store project-relative paths, size, digest for content-read fixtures, sample/stage identity, and the reason each fixture is safe and relevant. Freeze two tiers: a metadata/context tier and an extracted-content bioinformatics tier. The extracted tier must contain separate Shewanella L3 and L5 source-data fixtures plus an L3+L5 combined case; add source-only Cas9 and Class IIa fixtures where bounded data are available. All three source projects remain read-only.

- [ ] **Step 2: Safely materialize the content tier in scratch storage**

After Task 11 passes, list and validate every L3/L5 archive member before extraction: reject absolute paths, `..` traversal, links escaping the extraction root, devices/FIFOs/sockets, duplicate normalized paths, and member-count or expanded-size limits. Verify each archive digest and require sufficient free space for the declared expansion plus working outputs. Extract once into separate ignored roots `benchmark_runs/shewanella_extracted/L3/<archive_digest>/` and `benchmark_runs/shewanella_extracted/L5/<archive_digest>/`, write independent content manifests, then make both frozen trees read-only. Build the combined case only from manifest references to those two immutable roots. Never extract into or modify `/Users/gaojian/Desktop/Shewanella_V2_Analysis`, and never commit raw data.

- [ ] **Step 3: Write protocol tests before the runner**

Assert that all three arms receive the same task, fixture manifest, model/runtime class, external tool surface, wall-time budget, and output contract; controlled differences are limited to no Vivarium instructions, frozen GitHub V1, or frozen V2. Require fresh isolated work directories, randomized arm order, opaque arm IDs, fixed seeds where supported, and zero writes to the source project. Fail if a task leaks the arm label, the gold oracle, another arm's output, or post-baseline V1 fixes.

- [ ] **Step 4: Freeze deterministic oracles and adversarial cases**

Include metadata cases for sample reconciliation, provenance capture, wrong-source correction, superseded-value sealing, context compaction, interruption recovery, append-only rollback, mixed identifiers/coordinates, missing required metadata, and a deliberately misleading stale note. Run end-to-end content cases separately on L3, separately on L5, and jointly on L3+L5 for format/QC detection, sample-to-read consistency, reproducible bounded preprocessing, cross-sample separation, biological claim boundaries, and truthful handling of insufficient evidence. Existing derived L3/L5 results are hidden from both arms and may be exposed only to deterministic/blind evaluators as frozen oracle material. Score machine-checkable facts and artifact structure deterministically. Biological-method and overclaim judgments use blind independent review; Vivarium's own Checker is never the sole evaluator.

- [ ] **Step 5: Implement the matched two-arm runner**

Run `no_skill`, `vivarium_v1_frozen`, and `vivarium_v2_frozen` arms from the same frozen case bundle. The no-skill arm retains ordinary agent tools and reasoning but receives no Vivarium instructions, state, memory, handoff, or generated artifacts. V1 is pinned to the pre-optimization Git commit; V2 is pinned to the Task 11 release candidate. Preserve every prompt, tool receipt, output digest, exit status, elapsed time, and recovery event under immutable run directories. A failed or timed-out run remains in the denominator.

- [ ] **Step 6: Run the benchmark only after Task 11 passes**

Use paired cases and at least two independent repetitions per arm when budget permits. If the available sample is smaller, label results exploratory and do not claim statistical superiority. Report paired binary differences, effect sizes, bootstrap confidence intervals or exact sign tests implemented with the standard library, and the full missing/failure accounting.

- [ ] **Step 7: Write the detailed Markdown evaluation**

Write separate Chinese and English reports with identical result tables, claim status, and limitations. Each must contain: `Keywords`; `Project Status`; `Long-term Maintenance`; frozen protocol; source-data safety statement; fixture table; arm-equivalence checks; per-case raw outcomes; deterministic and blind-review rubrics; correctness/evidence/drift/rollback/recovery/bioinformatics/cost results; failure taxonomy; sensitivity analyses; limitations; clean-room statement; and an explicit conclusion separating demonstrated benefit, no detectable difference, and untested claims. `Project Status` records version, maturity, tested/untested capabilities, and last verification date. `Long-term Maintenance` states the ongoing semver/CHANGELOG/compatibility-test/benchmark-refresh policy without promising unsupported release dates. Link every aggregate to machine-readable run artifacts.

- [ ] **Step 8: Independently audit the comparison**

Dispatch a fresh adversarial reviewer to check leakage, cherry-picking, unequal budgets, non-independent grading, excluded failures, and claims unsupported by sample size. Any Critical/Important finding reopens the protocol or report before publication.

- [ ] **Step 9: Commit benchmark protocol and report**

```bash
git add benchmarks/v2/multi_project tests/v2/test_benchmark_protocol.py docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.zh-CN.md docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.en.md
git commit -m "test: compare vivarium v1 v2 and no-skill baselines"
```

### Task 13: Optimize V1 from development failures and verify on held-out projects

**Files:**
- Modify: `skills/vivarium/SKILL.md`
- Modify: `skills/vivarium/scripts/orchestrate.py`
- Modify: selected existing `skills/vivarium-*/SKILL.md` and scripts only where Task 12 identifies a reproduced V1 defect
- Create: `tests/v1_regression/`
- Modify: `docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.zh-CN.md`
- Modify: `docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.en.md`

**Interfaces:**
- Consumes: the frozen Task 12 baseline, a pre-declared development split, and reproduced V1 failures.
- Produces: minimal backward-compatible V1 fixes, regression tests, and a held-out evaluation that never uses V2-only state as hidden assistance.

- [ ] **Step 1: Freeze development and held-out splits before editing V1**

Use case families rather than individual files as the split unit so near-duplicate L3/L5 or project-derived cases cannot cross-contaminate. Record the split digest in the benchmark manifest. Never inspect held-out arm outputs while selecting fixes.

- [ ] **Step 2: Convert each development failure into a failing V1 regression test**

Require a concrete V1 defect with reproducible input, expected oracle, and observed failure. Do not backport the V2 architecture wholesale or change behavior merely because V2 scored higher. Preserve GitHub 1.0 CLI and sub-skill compatibility.

- [ ] **Step 3: Apply minimal V1 code and workflow fixes**

Fix only demonstrated issues in routing, provenance, input validation, manifest updates, error handling, or sub-skill guidance. Use the existing V1 scripts where they are correct. No deletion of V1 APIs, no silent migration to V2, and no tuning against held-out answers.

- [ ] **Step 4: Re-run development regressions and the original V1 suite**

All new tests must pass and all frozen Task 1 legacy characterization tests must remain green. Record exact code/process changes and which benchmark failure each change addresses.

- [ ] **Step 5: Run `vivarium_v1_optimized` on the held-out split once**

Use the same blinded budgets and evaluator pipeline as Task 12. Keep the original frozen V1 results in the report; never replace them. Report pre/post effect sizes, failures, regressions, and uncertainty without claiming improvements outside the evaluated tasks.

- [ ] **Step 6: Independently audit V1 optimization and the final report**

Check for leakage, cherry-picking, task-specific hard-coding, V2 artifact reuse, backward incompatibility, and unsupported generalization. Critical/Important findings require fixes and a fresh held-out case family, not repeated tuning on the same answers.

- [ ] **Step 7: Commit V1 hardening and the final comparative report**

```bash
git add skills tests/v1_regression docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.zh-CN.md docs/superpowers/benchmarks/2026-07-18-vivarium-v1-v2-multi-project-evaluation.en.md
git commit -m "fix: harden vivarium v1 from blinded benchmark failures"
```

### Task 14: Publish an evidence-led GitHub interface for Claude Code and Codex

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `install.sh`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Create: `docs/CLAUDE_CODE.md`
- Create: `docs/CODEX.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/BENCHMARKS.zh-CN.md`
- Create: `docs/BENCHMARKS.en.md`
- Create: `tests/repository/test_distribution_contract.py`

**Interfaces:**
- Consumes: audited Task 12/13 benchmark artifacts, the released V1/V2 compatibility surface, current official Claude Code plugin guidance, and current official Codex skill/customization guidance.
- Produces: a truthful bilingual repository landing page and tested dual-runner installation/usage documentation without changing scientific claims or hiding negative benchmark results.

- [ ] **Step 1: Verify current dual-runner distribution rules**

Use current official product documentation, not memory, to verify Claude Code plugin/marketplace structure and Codex skill discovery/install conventions. Record the verification date and direct documentation links. Keep marketplace metadata runner-specific; portability must live in the skill folder, scripts, and documented install paths.

- [ ] **Step 2: Write repository-contract tests first**

Test version consistency, local relative links, required bilingual sections, dry-run installation targets, executable permissions, clean-room independence, and that every benchmark claim maps to a frozen report/table artifact. The installer must never silently overwrite an existing installation and must support explicit Claude Code and Codex destinations.

- [ ] **Step 3: Rebuild the README information architecture**

Lead with the problem and verified outcome, then provide separate quick starts for Claude Code and Codex, a Mermaid architecture diagram, V1-compatible versus V2 control-plane boundaries, Maker/Checker/rollback/memory-drift/bioinformatics/cluster-static capabilities, and a concise example workflow. Add synchronized `Keywords`, `Project Status`, and `Long-term Maintenance` modules to both languages. The status module exposes version, maturity, support matrix, last verification date, and known limitations; the maintenance module commits to long-term semver/CHANGELOG/compatibility-test/benchmark-refresh practice without inventing release dates. Keep Chinese and English pages equivalent rather than allowing one to become stale.

- [ ] **Step 4: Publish benchmark results without marketing leakage**

Generate the summary table from Task 12/13 machine-readable results. Show no-skill, frozen V1, frozen V2, and optimized V1; include sample counts, uncertainty, failures/timeouts, costs, held-out status, and links to the detailed report. Separate `demonstrated`, `no detectable difference`, `regressed`, and `not tested` claims. Never write “better” or “safer” from architecture alone.

- [ ] **Step 5: Document logic and operational boundaries**

Explain event ledgers, complete-cut commits, Maker/Checker isolation, sealed fact correction, bounded handoff, rollback/fork, bioinformatics validators, and why live cluster mutation remains Phase B. Include migration, troubleshooting, update, uninstall/soft-removal, and V1 fallback instructions for both runners.

- [ ] **Step 6: Run dual-runner smoke tests and link checks**

Install into fresh temporary Claude Code and Codex roots using dry-run/temporary targets, invoke the skill discovery entrypoint, verify V1 legacy commands and V2 opt-in routing, and ensure no repository source or user configuration is overwritten. Run all repository-contract and existing V1/V2 tests.

- [ ] **Step 7: Adversarially audit the GitHub presentation**

Use independent reviewers for scientific claim accuracy, benchmark/statistical presentation, Claude Code installation, and Codex installation. Critical/Important findings block publication. The audit must explicitly search for benchmark cherry-picking, unsupported cluster claims, V1/V2 ambiguity, broken commands, and one-runner-only assumptions.

- [ ] **Step 8: Commit the dual-runner GitHub interface**

```bash
git add README.md README.en.md install.sh .claude-plugin docs tests/repository/test_distribution_contract.py
git commit -m "docs: publish dual-runner vivarium benchmark and architecture"
```

## Phase B exclusion

This plan intentionally does not implement real scheduler submission, cancellation, hold, release, smoke validation, profile activation, remote transport, or site accounting. Those operations require a separate site-qualified specification and plan built from real qsub/csub evidence. The Phase A public API must continue to fail closed for them.

## Spec coverage matrix

| Reviewed design area | Implementation task |
|---|---|
| Canonical events, hashes, torn tails, recovery | Tasks 2-4 |
| Closed reducers, complete-cut, abort, rollback/fork | Tasks 3-4 |
| Agent-only/local completion classification and proof | Task 5 |
| Maker/Validator/Checker isolation and quorum | Task 6 |
| Facts, decisions, memory sealing, self-learning gates, HandoffSnapshot | Task 7 |
| Typed bio artifacts, workflow seams, statistics, claims, database identity | Task 8 |
| qsub/csub static profiles, arrays, fake scheduler, live-operation denial | Task 9 |
| Legacy compatibility, V2 CLI, append-only migration | Tasks 1 and 10 |
| Clean-room independence, fault matrix, release evidence | Task 11 |
| Blinded multi-project no-skill/V1/V2 comparison | Task 12 |
| Benchmark-driven backward-compatible V1 hardening | Task 13 |
| Evidence-led Claude Code and Codex GitHub interface | Task 14 |

## Execution order and rollback boundary

Tasks 1-3 create no external side effects and can be reverted by returning the wrapper to legacy routing. Tasks 4-7 write only new V2 project directories and never mutate a legacy manifest. Tasks 8-9 are validators/static adapters with no real external mutations. Task 10 makes V2 user-visible but remains opt-in under the `v2` prefix. Task 11 is the release gate; if it fails, the existing legacy skill remains the default and all V2 data stays append-only and auditable.
