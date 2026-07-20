# vivarium

> **English** ｜ [中文](README.md)
>
> A durable analysis-execution system for local comparative genomics, delivered as a Claude Code skill set.

## Overview

**vivarium** is a Claude Code skill set for conducting comparative-genomics analyses locally. Given a set of genome assemblies and an analysis goal, the system plans the analysis as a stage graph (DAG), executes each stage in a `bio_tools` conda environment, and returns publication-grade figures and tables together with methods-ready provenance. The system adopts a **hybrid-execution** model: lightweight analyses (assembly QC, ANI/AAI, alignment-to-tree, sequence search, plotting) run in place, whereas computationally intensive or long-running stages (de novo assembly, eggNOG/dbCAN functional annotation, OrthoFinder orthology inference, large phylogenies, PAML selection tests) are emitted as executable commands for the user to run locally or on a compute cluster, with their outputs ingested and interpreted on return.

Since 2.0, the execution layer is provided by a **durable, crash-safe, event-sourced** kernel (see the next section). Whereas 1.0 recorded pipeline state in a mutable JSON manifest (`run_manifest.json`)—which a killed process, a truncated write, or cross-stage state distortion could silently corrupt—2.0 replaces it with an append-only event ledger: every stage's real output is sealed and appended to the ledger, which constitutes the single authoritative source of pipeline state. All 1.0 analysis scripts remain independently usable; 2.0 drives them as durable stages through a generic adapter, leaving their default behaviour unchanged.

vivarium is the analytical counterpart of the manuscript-preparation skill set [`scriptorium`](https://github.com/Jason-0409-G/scriptorium) (research-to-paper): scriptorium turns research into manuscripts; vivarium turns genomes into results.

## The 2.0 durable execution kernel

2.0 models the comparative-genomics pipeline as an **event-sourced state machine** engineered for deterministic recovery, pre-commit validation, and resource-aware scheduling.

**Event-sourced ledger.** Each stage's execution output is encoded as restricted RFC-8785/JCS canonical JSON, digested with domain-separated SHA-256, and appended to an append-only JSONL ledger; writes follow a file-before-directory fsync ordering and quarantine any torn tail. After an interruption at any point, the system reconstructs pipeline state byte-deterministically from the ledger and is idempotent over already-committed stages, which are not re-executed.

**C-1 commit gate.** Before a stage enters COMMITTED, four durable evidence objects—the evidence bundle, the success-completion record, the quorum-pass decision, and the completion proof—are re-validated, and all four must bind to a committed run/cut/claim/contract. An empty output or a non-zero exit code is intercepted before commit and never enters the ledger, precluding a failed stage from contaminating downstream state.

**Resource-aware routing.** `probe_device()` probes local core count, physical memory, and the presence of a cluster scheduler (sbatch/qsub/bsub); `route_stage()` then assigns each stage an execution locus:
- `local_inline` — the required tools are installed and the resources fit; the stage runs in place and commits;
- `cluster` — the stage exceeds local capacity but a scheduler exists; a directly submittable sbatch/qsub job script is generated;
- `scaffold_local` — a tool is missing or resources are insufficient and no scheduler exists; a command is emitted for the user to run externally, and the output is validated and ingested on return.

Routing is a resource-aware heuristic (conservatively deferring stages that exceed capacity), not a precise runtime prediction; job-script generation is implemented, while automatic submission to and polling of a cluster are deferred to a later release.

**Drivable, recoverable DAG.** `vivarium v2 plan/run` expands the four goals (`compare-genomes` / `phylogeny` / `selection` / `full`) into an ordered stage graph in which each stage carries its exact command, expected outputs, dependency edges, and routing decision. Driving runs the in-place stages automatically and pauses at the first stage requiring manual intervention or cluster submission, pre-creating its workspace; after the user ingests the output, driving again resumes from the durable ledger and continues.

```bash
# Print device probe, per-stage routing decisions, exact commands, and expected outputs
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    plan --root ./store --goal compare-genomes --genomes ./genomes

# Drive the pipeline: in-place stages run and commit; scaffold/cluster stages pause for the user
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    run  --root ./store --goal compare-genomes --genomes ./genomes
```

The integration of the kernel with the 1.0 scripts is documented in [`docs/V1_V2_INTEGRATION.zh-CN.md`](docs/V1_V2_INTEGRATION.zh-CN.md).

## Skills

| Skill | Function | In place / scaffolded |
|---|---|---|
| **`vivarium`** | Umbrella orchestrator: goal → analysis DAG → sub-skill chaining → durable-ledger tracking → pause/resume at heavy stages | coordinates |
| **`vivarium-prep`** | Assembly QC (contigs / N50 / GC / completeness); annotation (Prokka → eggNOG / dbCAN) | `stats` in place; assembly / eggNOG / dbCAN scaffolded |
| **`vivarium-compare`** | Genome relatedness (ANI/AAI via FastANI / EzAAI); orthology (OrthoFinder); synteny (MUMmer) | ANI / AAI / synteny in place; OrthoFinder scaffolded |
| **`vivarium-phylo`** | Align → trim → infer tree (MAFFT / trimAl / IQ-TREE); selection (PAML dN/dS) | `tree` in place; PAML scaffolded |
| **`vivarium-search`** | Sequence-similarity search (BLAST / DIAMOND / HMMER) | in place |
| **`vivarium-report`** | Publication-grade figures and tables (Python matplotlib / R ggplot2); export to SVG + PDF + TIFF at 600 dpi | in place |

Each skill is independently triggerable; the umbrella `vivarium`, or the 2.0 kernel, composes them into an end-to-end pipeline.

## Benchmarks

### 1 · Skill-efficacy benchmark (with-skill vs. no-skill baseline)

Four representative tasks (search / compare / phylogeny / report) were evaluated under an identical prompt and an identical `bio_tools` environment, with the presence of the skill as the only manipulated variable. Tasks were executed by claude-opus-4-8 (general-purpose sub-agents), once per configuration (single-machine, single-run; directional evidence rather than a powered statistical claim). Full data and per-assertion evidence are in [`benchmark/benchmark.md`](benchmark/benchmark.md).

| Metric | With skill | No-skill baseline | Δ |
|---|---|---|---|
| **Assertion pass rate** | **100%** | 82% | **+18 pt** |
| **Wall-clock (mean)** | **72 s** | 97 s | **≈26% faster** |
| Output tokens (mean) | 54.4 k | 53.2 k | +2% (one-time SKILL.md read) |

| Task | Pass (skill) | Pass (baseline) | Where the skill differs |
|---|---|---|---|
| search · homologues of 3 query proteins | 5/5 | 4/5 | baseline left 8 BLAST-DB binaries in the deliverables directory; the skill builds the database in a temporary directory |
| compare · 4-genome ANI + same-species call | 4/4 | 4/4 | parity on correctness; the skill is ≈37% faster and returns a clean matrix with no residual logs |
| phylogeny · ML tree from 8 groEL sequences | 4/4 | 4/4 | parity; both correctly reported the tree as unresolvable (near-identical sequences), avoiding overstatement |
| report · publication-grade ANI heatmap | 4/4 | **2/4** | baseline exported a screen-resolution PNG with no 600 dpi TIFF; the skill consistently exports SVG + PDF + TIFF (600 dpi, LZW) |

**Interpretation.** The skill set matches a careful baseline on biological correctness but diverges where publishability and reproducibility are at stake: (i) every run records a `tool + version + command` provenance footer, which an unguided run logs inconsistently; (ii) publication-grade output is consistently editable SVG + PDF + 600 dpi TIFF in a restrained, Nature-style convention, whereas the baseline produced a screen-resolution raster; (iii) the deliverables directory contains only results, scratch databases being confined to temporary directories; and (iv) invoking hardened bundled scripts rather than re-deriving command-line flags reduces wall-clock time by ≈26%.

### 2 · Durability and memory-consistency benchmark (2.0 vs. no-skill baseline)

To evaluate 2.0's central claim—that an event-sourced ledger acting as the single authoritative source eliminates cross-stage memory drift—a multi-stage comparative-genomics task was designed (per-genome assembly stats → all-vs-all ANI → same-species-pair call → a written summary citing prior values → an end-of-task recall of key values from memory). With "driven through the 2.0 durable kernel" as the manipulated variable, we measure token consumption, output quantity and hygiene, memory consistency (agreement between the end recall and the agent's own computed values), and academic completeness (provenance and reproducibility). The methodology mirrors the 1.0 benchmark (single-machine, single-run; directional evidence). Grading was performed by an independent claude-opus-4-8[1m] agent that recomputed every value. The full design, per-item scoring, and telemetry are in [`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md).

| Metric | No-skill baseline | 2.0 durable loop |
|---|---|---|
| correctness | **1.00** | 0.98 |
| memory_drift | 1.00 | 1.00 |
| academic_completeness | 0.95 | 0.95 |
| output_hygiene | 0.95 | **1.00** |
| stages_completed | 4 | 3 (sealed + committed) |
| Output tokens (single run) | 11,294 | **10,327 (≈ −8.6%)** |
| Input tokens (single run) | 31,632 | 31,660 (≈ +0.1%) |

**Interpretation.** The two configurations score closely; the decisive difference is not the score but the **mechanism**. The baseline recalls its three key values **from memory** at the end (all three happened to be correct in this single run), so correctness is carried by the recollection itself and is stressed as context and stage count grow; the durable loop instead **reads the values back from committed/sealed stage outputs (the ledger is the memory)**, validated at commit by the C-1 four-evidence gate and pinned by sha256 object heads and a hash-chained event stream, so its correctness is independent of context length. Both configurations biologically correctly called exactly one same-species pair (*S. vesiculosa*_M7 + PB002_L5, ANI ≈ 98.5% — two strains of the same species). **Token consumption was measured per agent: driving the durable kernel added no overhead** — the durable loop actually emitted marginally fewer output tokens (10.3k vs 11.3k) with near-identical input, because the CLI performs stage orchestration and the model need not assemble tool calls one by one, offsetting the cost of reading back outputs and maintaining the ledger (single run; not extrapolated).

**Improvement over 1.0.** 1.0 had no durability, no ledger, recorded state in a mutable JSON manifest (`run_manifest.json`), and **never measured memory drift**. 2.0 replaces that manifest with an append-only event ledger — byte-deterministically reconstructible after a crash, idempotent over committed stages, and constituting the single authoritative source of pipeline state — thereby turning "recall" into a read-back of immutable committed facts. That substitution is precisely what lets 2.0 measure memory drift as a first-class metric.

*Single-run, directional evidence, not a powered statistical claim; memory drift is measured as recall-versus-own-computed consistency. The grader's embedded "zero same-species pairs" reference was itself mistaken — both runs' one-pair call is biologically correct (PB002_L5 is a second* S. vesiculosa *strain) — as recorded in `benchmark/benchmark_v2.md`.*

## Triggering accuracy

On a deliberately boundary-heavy routing set of 20 queries — including "render an *existing* tree" (→ report, not phylo), "ANI already computed, plot it" (→ report, not compare), whole-pipeline versus single-step requests, and four should-trigger-nothing negatives (writing methods, polishing an abstract, weather, summarising a PDF) — all six descriptions route correctly (**20/20 = 100%**). Each skill additionally ships `evals/trigger_evals.json` (67 should-/should-not-trigger queries in total), serving both as a triggering contract and as a regression guard; with an API key configured, these feed the official `skill-creator` optimiser directly via `run_loop.py --eval-set <file>`.

## Installation

**Option 1 · Plugin marketplace (recommended)**
```
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git
/plugin install vivarium@vivarium
/reload-plugins
```
> Use the full HTTPS URL to avoid clone failures when no SSH key is configured.

**Option 2 · Script (clone, then install locally)**
```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh            # copies skills/ into ~/.claude/skills/
```

## Update

This plugin uses **semantic versioning** (the `version` field in `.claude-plugin/plugin.json`). Users receive an update only when that version is incremented; what changed in each release is in [`CHANGELOG.md`](CHANGELOG.md).

**If installed from the marketplace**
```
/plugin marketplace update vivarium     # pull the latest catalog
/plugin update vivarium@vivarium        # install the new version
/reload-plugins                         # apply in this session (or restart)
```
Auto-update for the `vivarium` marketplace can also be enabled under `/plugin` → Marketplaces.

**If installed via the script**
```bash
cd vivarium   # the folder you cloned
git pull
bash install.sh
```

## Dependencies

Analysis tools must be available in a **`bio_tools` conda environment** (the skills never auto-install; missing tools are reported, not installed):
- QC / annotation: seqkit, Prokka, (CheckM2, Flye, eggNOG-mapper, dbCAN — optional / heavy)
- Comparison: FastANI, EzAAI, OrthoFinder, MUMmer4
- Phylogenetics: MAFFT, trimAl, IQ-TREE, FastTree, PAML (codeml), PAL2NAL
- Search: BLAST+, DIAMOND, HMMER
- Plotting: Python (pandas / matplotlib) or R (ggplot2 / svglite / ragg)

The 2.0 kernel is implemented in the standard library alone and adds no runtime dependency; the tools above are required only when the corresponding analysis stage runs in place.

## Design principles

- **Durability and deterministic recovery.** State is recorded in an append-only event ledger, reconstructible byte-deterministically after an interruption and idempotent over committed stages.
- **Pre-commit validation.** A stage commits only after passing the C-1 four-evidence gate; failed or empty outputs do not enter the ledger.
- **Hybrid execution.** Lightweight steps run in place; heavy steps are emitted as commands for the user to run — no unattended long jobs.
- **No automatic installation.** Missing tools or databases are surfaced for the user to decide upon.
- **Provenance (software versions recorded at every step).** Each script prints a uniform footer `=== vivarium-… done === / tool: <name>(<version>) / command: <exact command>`; the six analysis scripts and both plotting back-ends (matplotlib / ggplot2, with their versions) are unified, so output is methods-ready.
- **Figures serve the science.** No overstatement; an n = 1 observation is not extrapolated.
- **Soft deletion.** No `rm`; files requiring removal are moved to `_deleted/`.
- **Robust under weaker, non-Claude models.** Every step is "run this exact command and read its output"; analytical logic lives entirely in bundled scripts (FastANI / IQ-TREE / BLAST … plus the unified provenance footer), so the model neither assembles flags nor orchestrates multi-step tool calls. The set therefore remains stable on a non-Claude backend (e.g. `deepseek-v4-pro[1m]`, sub-agents on `deepseek-v4-flash`).

## License

See `LICENSE` (MIT).
