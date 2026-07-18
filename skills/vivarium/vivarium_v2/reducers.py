"""Public façade for the federated reducer pipeline.

Implementation is split by responsibility so replay, validity, and federation
can be reviewed independently while this module preserves the stable API.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ._federation import build_federated_state, federate
from ._project_replay import reduce_project_cut
from ._project_support import empty_project_state_root
from ._run_replay import reduce_run
from ._validity import reduce_project_validity, reduce_run_validity
from .events import Event
from .state import (
    FederatedState,
    ProjectPrefixes,
    ProjectSemanticCut,
    ProjectValidity,
    RunLocalState,
    RunValiditySlice,
)

ReduceRun = Callable[[Sequence[Event]], RunLocalState]
ReduceProjectCut = Callable[[ProjectPrefixes], ProjectSemanticCut]
ReduceProjectValidity = Callable[[ProjectSemanticCut], ProjectValidity]
ReduceRunValidity = Callable[
    [ProjectSemanticCut, ProjectValidity, RunLocalState], RunValiditySlice
]
Federate = Callable[
    [RunLocalState, ProjectSemanticCut, ProjectValidity, RunValiditySlice],
    FederatedState,
]

__all__ = [
    "Federate",
    "ReduceProjectCut",
    "ReduceProjectValidity",
    "ReduceRun",
    "ReduceRunValidity",
    "build_federated_state",
    "empty_project_state_root",
    "federate",
    "reduce_project_cut",
    "reduce_project_validity",
    "reduce_run",
    "reduce_run_validity",
]
