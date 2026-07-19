# Vivarium Loop Engineer V2 Adversarial Review Record

## Decision

- Gate: **PASS**
- Final independent closure reviews: **A = 0 Critical / 0 Major**, **B = 0 Critical / 0 Major**
- Audited semantic-content SHA-256: `de7d87902a1f2195cd8f9449d05f278a6388b2f333b43f2d706eab2225bf7b20`
- Current design SHA-256 after the metadata-only status-line update: `d5188d3d6d2d3c13b46d086f94c6fc69af44f09ddcbbe443c704c29aeaffcb13`
- Authorized next artifact: Phase A implementation plan only. Production implementation has not started.
- Deferred scope: site-qualified live cluster mutation (`submit/cancel/hold/release/smoke`) remains Phase B and disabled by default.

The status-line update changed no requirement, schema, algorithm, oracle, or phase boundary. The reviewed semantic body is otherwise byte-identical to the PASS artifact.

## Gate policy

Every completed review used the same threshold: PASS requires `0 Critical / 0 Major`. Minor findings could be recorded, but no Critical or Major could be waived. Reviewers were instructed to provide exact line references, a reproducible trace, impact, and a minimal fix; optional enhancements and missing Phase B site data were not gate findings.

## Audit history

| Completed gate | Result | Main categories closed before the next gate |
|---|---:|---|
| 1 | 5C / 10M / 3m — FAIL | role isolation, state ownership, irreversible side effects, evidence sealing |
| 2 | 0C / 5M — FAIL | atomic commit, recovery, dependency invalidation |
| 3 | 0C / 5M — FAIL | scheduler uncertainty, proof identity, checker quorum |
| 4 | 0C / 4M — FAIL | memory/fact lifecycle, handoff consistency |
| 5 | 0C / 6M — FAIL | completion classification, client containment, array identity |
| 6 | 0C / 4M — FAIL | project/run registration, post-commit evidence, reducers |
| 7 | 1C / 5M — FAIL | external mutation and complete-cut safety |
| 8 | 1C / 2M — FAIL | evidence durability and active reachability |
| 9 | 0C / 8M / 1m — FAIL | cluster activation, at-most-once transport, workflow seams |
| 10 | 1C / 6M / 1m — FAIL | canonical identity and recovery edge cases |
| 11 | 0C / 13M — FAIL | typed outcomes, memory dependency binding, cluster/static boundary |
| 12 | 0C / 3M / 3m — FAIL | complete-cut and validator/review sealing |
| 13 | 0C / 3M / 1m — FAIL | HandoffSnapshot and multi-run obligations |
| 14 | 0C / 2M / 3m — FAIL | reducer ownership and canonical state roots |
| 15 | 0C / 1M — FAIL | run tail versus project complete-cut federation |
| Federated closure | 0C / 3M — FAIL | full project validity cut, byte-level ledger hashes, commit-abort transition |
| Parallel final A | 0C / 2M — FAIL | run-specific validity input, durable post-commit observation intake |
| Parallel final B | 0C / 5M — FAIL | revision bootstrap, abort layer split, handoff projection, hypothesis family, database identity |
| Closure A | **0C / 0M — PASS** | both state/recovery findings verified closed; no new gate finding |
| Closure B | **0C / 0M — PASS** | all five domain findings verified closed; no new gate finding |

Two read-only review attempts were interrupted and are not counted as completed gates: one after the user clarified clean-room independence from bioSkills, and one when a domain-separator defect was found locally before the reviewer finished.

## Final closure evidence

### State, durability, and recovery

- A federated certificate binds a checksum-valid run prefix to the complete five-ledger `ProjectSemanticCut`.
- `project_validity_reducer` computes project closure; `run_validity_reducer` separately joins that closure with run-local dependency vectors. An unrelated fact or memory change does not alter the run-specific validity slice, while the full certificate still binds the new project cut.
- Event payload, event hash, record checksum, JCS bytes, LF framing, genesis rules, and torn-tail handling have fixed algorithms and two independently recomputed golden vectors.
- `STAGE_COMMIT_ABORTED` atomically closes the preparation and moves analysis through a closed reason-to-target map. Evidence integrity failure, evidence binding staleness, and validator report invalidity are distinct paths.
- A passive post-commit response is first durably inlined as a run-ledger inbox event. Before `COMPLETION_RECHECK_OPENED`, its run-local intake blocker already disables retrieval, handoff success, downstream commit, and external operations.

### Context, memory, and role separation

- Maker, Validator, Checker, Snapshotter, Broker, and Orchestrator capabilities are separated; deterministic hard gates cannot be overruled by Checker votes.
- Fact/source corrections, decision/policy changes, memory withdrawal, rollback, and completion recheck feed canonical invalidation reducers rather than an ever-growing handoff narrative.
- Superseded/retracted values remain sealed audit history and are excluded from default retrieval. Handoff is a deterministic bounded projection, not a source of truth or active scientific object.

### Bioinformatics correctness

- Typed artifact contracts cover sample identity, coordinate frames, mixed genetic codes, sequence canonicalization, database/tool identity, workflow seams, statistical design, multiple testing, claims, and report provenance.
- Hypothesis families are frozen before modeling as canonical member manifests. Results must cover every member exactly once, and validators recompute filtering and multiple-testing adjustment from the frozen family.
- Database assets use strong/weak `DatabaseIdentity`. Weak identity forces `cache_eligible=false`; it cannot silently reuse results under an unchanged release/path label.

### Cluster boundary

- Phase A may statically inspect executable bytes/metadata, lint profiles, render scripts, exercise interfaces, and use a fake scheduler.
- Phase A must not execute real `qsub/csub` help/version probes if they might mutate state, and must not submit, cancel, hold, release, or smoke-test a real job.
- Phase B requires site evidence, explicit validation authorization, a profile activation head, user enablement, transport containment, and fault-injection results. It is intentionally outside the current implementation plan.

### Independence from bioSkills

The GPTomics/bioSkills repository was used only as a design-study source. Vivarium has no runtime, build, installation, import, catalog, test, vendor, generated-source, or benchmark dependency on bioSkills. No bioSkills content is copied as an executable component.

## Mechanical checks

- Markdown fences are balanced.
- `git diff --no-index --check` produced no whitespace diagnostics; its exit status is nonzero only because the design is a new file compared with `/dev/null`.
- Python and Node independently reproduced both ledger golden vectors.
- Runtime/build/install/test tree search found no bioSkills dependency; design/review documentation retains only clean-room study and audit references.
- Production source files were not modified during design or review.
