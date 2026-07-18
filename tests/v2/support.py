from __future__ import annotations

from pathlib import Path

from skills.vivarium.vivarium_v2.project import COMMIT_CRASH_POINTS, PreparedCommit, ProjectStore


class FrozenClock:
    def __init__(self, value: str):
        self.value = value

    def __call__(self) -> str:
        return self.value


class InjectedCrash(RuntimeError):
    pass


def fixture_store_at_revision(root: Path, revision: int) -> ProjectStore:
    store = ProjectStore.init(root, FrozenClock("2026-07-18T00:00:00Z"))
    if revision:
        store.register_run("run-1", analysis_state="COMMITTING")
    namespaces = ("truth", "decision", "work", "memory", "run-registry")
    while store.capture()[0].project_revision < revision:
        store.append_fixture_event(
            namespaces[(store.capture()[0].project_revision - 1) % len(namespaces)]
        )
    return store


def valid_prepared_commit(
    store: ProjectStore, *, run_id: str = "run-1", **overrides
) -> PreparedCommit:
    if not store.capture()[1]:
        store.register_run(run_id, analysis_state="COMMITTING")
    return store.prepare_commit({"run_id": run_id, **overrides})


def prepared_fixture(root: Path) -> ProjectStore:
    store = ProjectStore.init(root, FrozenClock("2026-07-18T00:00:00Z"))
    store.register_run("run-1", analysis_state="COMMITTING")
    prepared = valid_prepared_commit(store)
    store._test_prepared_commit = prepared
    return store


def inject_once(store: ProjectStore, point: str) -> None:
    if point not in COMMIT_CRASH_POINTS:
        raise ValueError(point)
    fired = False

    def injector(observed: str) -> None:
        nonlocal fired
        if observed == point and not fired:
            fired = True
            raise InjectedCrash(point)

    store.fault_injector = injector
    try:
        store.complete_commit(store._test_prepared_commit)
    except InjectedCrash:
        pass
    finally:
        store.fault_injector = None
    if not fired:
        raise AssertionError(f"fault point was not reached: {point}")


__all__ = [
    "COMMIT_CRASH_POINTS",
    "FrozenClock",
    "fixture_store_at_revision",
    "inject_once",
    "prepared_fixture",
    "valid_prepared_commit",
]
