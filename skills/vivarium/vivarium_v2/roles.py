from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .canonical import domain_hash
from .errors import IntegrityError
from .evidence import EvidenceBundle, ValidatorSeal, validate_evidence_bundle


def _is_digest(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _strings(value: tuple[str, ...], field: str) -> None:
    if not isinstance(value, tuple) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise IntegrityError(f"{field} must be an immutable string tuple")


@dataclass(frozen=True)
class CapabilityReceipt:
    receipt_id: str
    role: str
    principal_id: str
    capability_namespace: str
    granted_capabilities: tuple[str, ...]
    live_capabilities: tuple[str, ...]
    unresolved_capabilities: tuple[str, ...]
    isolation_level: str

    def __post_init__(self) -> None:
        if self.role not in {"maker", "validator", "checker", "orchestrator"}:
            raise IntegrityError("capability receipt role is not closed")
        if self.isolation_level not in {"hard", "soft"}:
            raise IntegrityError("capability isolation level is not closed")
        for value, field in (
            (self.granted_capabilities, "granted_capabilities"),
            (self.live_capabilities, "live_capabilities"),
            (self.unresolved_capabilities, "unresolved_capabilities"),
        ):
            _strings(value, field)

    @property
    def capability_receipt_digest(self) -> str:
        return domain_hash(
            "vivarium-capability-receipt/v1",
            {
                "receipt_id": self.receipt_id,
                "role": self.role,
                "principal_id": self.principal_id,
                "capability_namespace": self.capability_namespace,
                "granted_capabilities": list(self.granted_capabilities),
                "live_capabilities": list(self.live_capabilities),
                "unresolved_capabilities": list(self.unresolved_capabilities),
                "isolation_level": self.isolation_level,
            },
        )


@dataclass(frozen=True)
class CheckerAssignment:
    assignment_id: str
    checker_id: str
    capability_namespace: str
    mission_digest: str
    rubric_digest: str
    acceptance_contract_digest: str
    evidence_bundle_digest: str
    execution_evidence_cut_digest: str
    validator_seal_digest: str
    completion_claim_digest: str
    capability_receipt_digest: str

    @property
    def checker_assignment_digest(self) -> str:
        return domain_hash("vivarium-checker-assignment/v1", self.__dict__)


@dataclass(frozen=True)
class CheckerReview:
    assignment_id: str
    checker_id: str
    capability_namespace: str
    outcome: str
    severities: tuple[str, ...]
    mission_digest: str
    rubric_digest: str
    acceptance_contract_digest: str
    evidence_bundle_digest: str
    execution_evidence_cut_digest: str
    validator_seal_digest: str
    completion_claim_digest: str
    capability_receipt_digest: str
    namespace_attestation_digest: str

    def __post_init__(self) -> None:
        if self.outcome not in {"pass", "repairable", "reject"}:
            raise IntegrityError("checker review outcome is not closed")
        _strings(self.severities, "severities")
        if any(value not in {"Info", "Minor", "Major", "Critical"} for value in self.severities):
            raise IntegrityError("checker review severity is not closed")

    @property
    def checker_review_digest(self) -> str:
        body = dict(self.__dict__)
        body["severities"] = list(self.severities)
        return domain_hash("vivarium-checker-review/v1", body)


@dataclass(frozen=True)
class QuorumPolicy:
    success_grade: str
    required_reviews: int
    require_hard_isolation: bool
    require_independent_namespaces: bool

    def __post_init__(self) -> None:
        if self.success_grade not in {"L1", "L2"}:
            raise IntegrityError("quorum success grade is not closed")
        if isinstance(self.required_reviews, bool) or self.required_reviews < 1:
            raise IntegrityError("quorum requires at least one review")
        if self.success_grade == "L2" and (
            self.required_reviews < 2 or not self.require_independent_namespaces
        ):
            raise IntegrityError("L2 requires two independent checker namespaces")

    @property
    def quorum_policy_digest(self) -> str:
        return domain_hash("vivarium-quorum-policy/v1", self.__dict__)


@dataclass(frozen=True)
class GateDecision:
    outcome: str
    reasons: tuple[str, ...]
    success_grade: str
    required_reviews: int
    accepted_review_digests: tuple[str, ...]
    quorum_policy_digest: str

    @property
    def gate_decision_digest(self) -> str:
        return domain_hash(
            "vivarium-gate-decision/v1",
            {
                "outcome": self.outcome,
                "reasons": list(self.reasons),
                "success_grade": self.success_grade,
                "required_reviews": self.required_reviews,
                "accepted_review_digests": list(self.accepted_review_digests),
                "quorum_policy_digest": self.quorum_policy_digest,
            },
        )


_ROLE_WRITE_TARGETS = {
    "maker": frozenset({"candidate_payload"}),
    "validator": frozenset({"validator_report", "evidence_seal"}),
    "checker": frozenset({"checker_review"}),
    "orchestrator": frozenset({"canonical_ledger"}),
}


def assert_role_write_allowed(role: str, target: str) -> None:
    if target not in _ROLE_WRITE_TARGETS.get(role, frozenset()):
        raise IntegrityError(f"{role} is not authorized to write {target}")


_CHECKER_PACKET_FIELDS = {
    "assignment_id",
    "checker_id",
    "capability_namespace",
    "mission_digest",
    "rubric_digest",
    "acceptance_contract_digest",
    "evidence_bundle_digest",
    "execution_evidence_cut_digest",
    "validator_seal_digest",
    "completion_claim_digest",
    "capability_receipt_digest",
}


def build_checker_assignment(
    packet: Mapping[str, Any], receipt: CapabilityReceipt
) -> CheckerAssignment:
    if not isinstance(packet, Mapping) or set(packet) != _CHECKER_PACKET_FIELDS:
        raise IntegrityError("checker packet contains forbidden or missing fields")
    if receipt.role != "checker" or (
        packet["checker_id"], packet["capability_namespace"], packet["capability_receipt_digest"]
    ) != (
        receipt.principal_id,
        receipt.capability_namespace,
        receipt.capability_receipt_digest,
    ):
        raise IntegrityError("checker packet does not bind its capability receipt")
    for field in _CHECKER_PACKET_FIELDS - {
        "assignment_id",
        "checker_id",
        "capability_namespace",
    }:
        if not _is_digest(packet[field]):
            raise IntegrityError("checker packet contains an invalid authority digest")
    return CheckerAssignment(**dict(packet))


def build_checker_review(
    assignment: CheckerAssignment,
    receipt: CapabilityReceipt,
    *,
    outcome: str = "pass",
    severities: Sequence[str] = (),
) -> CheckerReview:
    if (
        receipt.capability_receipt_digest != assignment.capability_receipt_digest
        or receipt.principal_id != assignment.checker_id
        or receipt.capability_namespace != assignment.capability_namespace
    ):
        raise IntegrityError("checker review receipt does not bind its assignment")
    attestation = domain_hash(
        "vivarium-checker-namespace-attestation/v1",
        {
            "assignment_digest": assignment.checker_assignment_digest,
            "capability_receipt_digest": receipt.capability_receipt_digest,
            "capability_namespace": receipt.capability_namespace,
        },
    )
    return CheckerReview(
        assignment.assignment_id,
        assignment.checker_id,
        assignment.capability_namespace,
        outcome,
        tuple(severities),
        assignment.mission_digest,
        assignment.rubric_digest,
        assignment.acceptance_contract_digest,
        assignment.evidence_bundle_digest,
        assignment.execution_evidence_cut_digest,
        assignment.validator_seal_digest,
        assignment.completion_claim_digest,
        assignment.capability_receipt_digest,
        attestation,
    )


def decide_gate(
    store: Any,
    bundle: EvidenceBundle,
    validator_seal: ValidatorSeal,
    *,
    mission_digest: str,
    rubric_digest: str,
    acceptance_contract_digest: str,
    completion_claim_digest: str,
    assignments: Sequence[CheckerAssignment],
    reviews: Sequence[CheckerReview],
    capability_receipts: Sequence[CapabilityReceipt],
    policy: QuorumPolicy,
    validator_hard_gates_passed: bool = True,
) -> GateDecision:
    reasons: set[str] = set()
    try:
        validate_evidence_bundle(store, bundle)
    except IntegrityError:
        reasons.add("evidence_bundle_invalid")
    if (
        not validator_hard_gates_passed
        or validator_seal.validation_outcome != "pass"
    ):
        reasons.add("hard_validator_failure")
    if (
        validator_seal.evidence_bundle_digest != bundle.evidence_bundle_digest
        or validator_seal.execution_evidence_cut_digest
        != bundle.execution_evidence_cut_digest
    ):
        reasons.add("validator_evidence_binding_mismatch")
    assignment_ids = [item.assignment_id for item in assignments]
    namespaces = [item.capability_namespace for item in assignments]
    if len(assignment_ids) != len(set(assignment_ids)):
        reasons.add("duplicate_assignment")
    if len(namespaces) != len(set(namespaces)):
        reasons.add("duplicate_namespace")
    receipts = {
        item.capability_receipt_digest: item for item in capability_receipts
    }
    expected = {
        "mission_digest": mission_digest,
        "rubric_digest": rubric_digest,
        "acceptance_contract_digest": acceptance_contract_digest,
        "evidence_bundle_digest": bundle.evidence_bundle_digest,
        "execution_evidence_cut_digest": bundle.execution_evidence_cut_digest,
        "validator_seal_digest": validator_seal.validator_seal_digest,
        "completion_claim_digest": completion_claim_digest,
    }
    assignments_by_id: dict[str, CheckerAssignment] = {}
    assignment_validity: dict[str, bool] = {}
    for assignment in assignments:
        assignments_by_id.setdefault(assignment.assignment_id, assignment)
        assignment_valid = True
        if any(getattr(assignment, field) != value for field, value in expected.items()):
            reasons.add("assignment_binding_mismatch")
            assignment_valid = False
        receipt = receipts.get(assignment.capability_receipt_digest)
        if receipt is None or (
            receipt.role != "checker"
            or receipt.principal_id != assignment.checker_id
            or receipt.capability_namespace != assignment.capability_namespace
        ):
            reasons.add("assignment_capability_mismatch")
            assignment_validity.setdefault(assignment.assignment_id, False)
            continue
        if receipt.live_capabilities or receipt.unresolved_capabilities:
            reasons.add("live_or_unresolved_capabilities")
            assignment_valid = False
        if receipt.isolation_level != "hard":
            reasons.add("soft_isolation")
            assignment_valid = False
        assignment_validity.setdefault(assignment.assignment_id, assignment_valid)
    accepted = []
    accepted_namespaces: set[str] = set()
    reviewed_assignments: set[str] = set()
    for review in reviews:
        assignment = assignments_by_id.get(review.assignment_id)
        if assignment is None or review.assignment_id in reviewed_assignments:
            reasons.add("duplicate_or_unknown_review_assignment")
            continue
        reviewed_assignments.add(review.assignment_id)
        review_valid = assignment_validity.get(review.assignment_id, False)
        if any(severity in {"Major", "Critical"} for severity in review.severities):
            reasons.add("major_or_critical_finding")
            review_valid = False
        if review.outcome != "pass":
            reasons.add("checker_review_not_pass")
            review_valid = False
        assignment_fields = {
            field: getattr(assignment, field)
            for field in expected
        }
        if any(getattr(review, field) != value for field, value in assignment_fields.items()) or (
            review.checker_id,
            review.capability_namespace,
            review.capability_receipt_digest,
        ) != (
            assignment.checker_id,
            assignment.capability_namespace,
            assignment.capability_receipt_digest,
        ):
            reasons.add("review_binding_mismatch")
            review_valid = False
        receipt = receipts.get(review.capability_receipt_digest)
        expected_attestation = (
            domain_hash(
                "vivarium-checker-namespace-attestation/v1",
                {
                    "assignment_digest": assignment.checker_assignment_digest,
                    "capability_receipt_digest": review.capability_receipt_digest,
                    "capability_namespace": review.capability_namespace,
                },
            )
            if assignment is not None
            else ""
        )
        if (
            receipt is None
            or receipt.role != "checker"
            or review.namespace_attestation_digest != expected_attestation
        ):
            reasons.add("namespace_attestation_invalid")
            review_valid = False
        if review_valid:
            accepted.append(review.checker_review_digest)
            accepted_namespaces.add(review.capability_namespace)
    if len(accepted) < policy.required_reviews:
        reasons.add("insufficient_quorum")
    if policy.success_grade == "L2" and len(accepted_namespaces) < 2:
        reasons.add("insufficient_independent_namespaces")
    if policy.success_grade == "L1" and policy.required_reviews == 1:
        if not policy.require_hard_isolation:
            reasons.add("l1_single_review_requires_hard_isolation")
    ordered_reasons = tuple(sorted(reasons))
    return GateDecision(
        "pass" if not ordered_reasons else "fail",
        ordered_reasons,
        policy.success_grade,
        policy.required_reviews,
        tuple(sorted(accepted)),
        policy.quorum_policy_digest,
    )


__all__ = [
    "CapabilityReceipt",
    "CheckerAssignment",
    "CheckerReview",
    "GateDecision",
    "QuorumPolicy",
    "assert_role_write_allowed",
    "build_checker_assignment",
    "build_checker_review",
    "decide_gate",
]
