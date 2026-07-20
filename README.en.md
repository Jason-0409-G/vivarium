<p align="center">
  <a href="docs/media/vivarium-v2-durable-loop-4k.png">
    <img src="docs/media/vivarium-v2-durable-loop-4k.png" alt="Vivarium 2.0 event-sourced, crash-safe, evidence-gated execution mechanism" width="100%">
  </a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f.svg?style=flat-square" alt="MIT license"></a>
  <a href="https://github.com/Jason-0409-G/vivarium/releases"><img src="https://img.shields.io/badge/release-v2.0.1-0969da.svg?style=flat-square" alt="release v2.0.1"></a>
  <img src="https://img.shields.io/badge/clients-Claude_Code_%7C_Codex-24292f.svg?style=flat-square" alt="Claude Code and Codex">
  <img src="https://img.shields.io/badge/skills-6-0ea5e9.svg?style=flat-square" alt="6 skills">
  <img src="https://img.shields.io/badge/status-actively_maintained-2ea44f.svg?style=flat-square" alt="actively maintained">
  <a href="README.md"><img src="https://img.shields.io/badge/language-中文-2563eb.svg?style=flat-square" alt="中文 README"></a>
</p>

<p align="center">
  <a href="#project-status">Status</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#running-the-complete-workflow">Quick start</a> ·
  <a href="#core-mechanism-and-technical-positioning">Core mechanism</a> ·
  <a href="#skill-index">Skill index</a> ·
  <a href="#benchmarks">Benchmarks</a> ·
  <a href="README.md">中文</a>
</p>

---

**vivarium is a dual-client workflow skill set and durable execution kernel for comparative genomics.** It converts analytical goals into validated, recoverable, and auditable stage graphs while providing the same workflow contracts in Claude Code and Codex.

## Project status

| Item | Current status |
|---|---|
| **Maintenance** | **Actively maintained and iterated**; subsequent releases will respond to real-data benchmarks, cross-client compatibility tests, and user feedback |
| **Current release** | `v2.0.1`; 2.0 is the main development line, while the 1.0 analysis scripts remain independently usable |
| **Supported clients** | Claude Code plugin and Codex skills; both clients use the same `SKILL.md` workflow contracts |
| **Version record** | Semantic versioning, [`CHANGELOG.md`](CHANGELOG.md), and [GitHub Releases](https://github.com/Jason-0409-G/vivarium/releases) |
| **Development roadmap** | Inputs, implementation, deliverables, acceptance criteria, dependencies, risks, and status for 14 public tasks are documented in [`docs/VIVARIUM_V2_TASKS.zh-CN.md`](docs/VIVARIUM_V2_TASKS.zh-CN.md) |

> Incomplete capabilities are identified explicitly in the roadmap and release notes. Automated cluster-job submission and polling remain in scope for a later release.

## Installation

Claude Code and Codex are peer-supported clients. They expose the same six workflow capabilities and differ only in distribution and update mechanisms.

| | **Claude Code** | **Codex** |
|---|---|---|
| **Recommended entry point** | Plugin marketplace | `$skill-installer` |
| **Distribution unit** | One plugin containing the umbrella skill and five sub-skills | Six independent skill paths |
| **Default location** | Claude Code plugin cache | `$CODEX_HOME/skills`, defaulting to `~/.codex/skills` |

### Claude Code

Run these commands in Claude Code:

```text
/plugin marketplace add Jason-0409-G/vivarium
/plugin install vivarium@vivarium
/reload-plugins
```

The repository currently uses `master` as its default branch. To pin the branch explicitly, replace the first command with:

```text
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git#master
```

### Codex

Paste the following request into Codex:

```text
Use $skill-installer to install these paths from repo Jason-0409-G/vivarium using --ref master:
skills/vivarium
skills/vivarium-prep
skills/vivarium-compare
skills/vivarium-phylo
skills/vivarium-search
skills/vivarium-report
```

Keep `--ref master` because `$skill-installer` otherwise attempts `main`. Restart Codex if the new skills do not appear immediately.

<details>
<summary><strong>Local script installation for Claude Code, Codex, or both</strong></summary>

```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh --target claude   # installs into ~/.claude/skills/
bash install.sh --target codex    # installs into $CODEX_HOME/skills
bash install.sh --target both     # installs into both clients
```

The installer does not delete an existing skill in place. It first renames the existing directory to a timestamped backup and then writes the new copy.

</details>

<details>
<summary><strong>Codex installation with user-level symlinks</strong></summary>

```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
mkdir -p "$HOME/.agents/skills"
for skill in vivarium vivarium-prep vivarium-compare vivarium-phylo vivarium-search vivarium-report; do
    ln -s "$PWD/skills/$skill" "$HOME/.agents/skills/$skill"
done
```

This approach keeps one source checkout; subsequent `git pull` operations update every linked skill. To enable the skills only in the current repository, create the links under the repository-level `.agents/skills` directory instead.

</details>

## Updating

Formal releases are identified by the `version` field in `.claude-plugin/plugin.json`. Pushing code to `master` without incrementing this field does not publish a new plugin version.

| Installation method | Update procedure |
|---|---|
| **Claude Code marketplace** | `/plugin marketplace update vivarium` → `/plugin update vivarium@vivarium` → `/reload-plugins` |
| **Codex `$skill-installer`** | Synchronize the same six paths again and retain `--ref master` |
| **Local script copy** | Run `git pull`, then rerun `bash install.sh --target claude`, `codex`, or `both` |
| **Codex symlinks** | Run `git pull` in the repository targeted by the links |

Claude Code can enable automatic updates for `vivarium` under `/plugin` → Marketplaces. Reload the plugin or restart the relevant client if the active session still reports an older version.

## Running the complete workflow

The umbrella `vivarium` skill drives the `full` goal of the 2.0 durable kernel. Explicit invocation is recommended so that a broad request is not routed to a single-step sub-skill.

| **Claude Code** | **Codex** |
|---|---|
| `/vivarium:vivarium` | `$vivarium` |

**Claude Code**

```text
/vivarium:vivarium Run the complete vivarium 2.0 durable workflow over ./genomes. Use the full goal, print the DAG and local/cluster routing before execution, persist state under ./vivarium_store, run eligible local stages, and pause at cluster or scaffold stages with the exact command, expected artifacts, and collection path.
```

**Codex**

```text
Use $vivarium to run the full vivarium 2.0 durable workflow over ./genomes. Use the full goal, print the DAG and local/cluster routing before execution, persist state under ./vivarium_store, run eligible local stages, and pause at cluster or scaffold stages with the exact command, expected artifacts, and collection path.
```

The same kernel can be driven directly from the repository root:

```bash
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    plan --root ./vivarium_store --goal full --genomes ./genomes

PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    run --root ./vivarium_store --goal full --genomes ./genomes
```

The current `full` goal expands to assembly statistics → annotation → ANI → AAI → orthology → synteny → phylogeny → heatmap. Sequence search and PAML selection analysis require additional inputs and are not added automatically when query sequences, databases, or codon alignments are absent.

## Core mechanism and technical positioning

LLM-mediated long workflows have two classes of state risk. Mutable manifests can become inconsistent after interruption or partial writes, and model context can diverge from computed artifacts during cross-stage recitation. vivarium 2.0 moves workflow state from model memory and mutable files into an append-only, hash-chained event ledger, with fail-closed evidence validation before commit.

### Durable loop

| Stage | Function | Verifiable result |
|---|---|---|
| **PLAN** | Expand a goal into an ordered DAG | Exact commands, expected artifacts, and dependency edges |
| **ROUTE** | Probe CPU, memory, tools, and schedulers | `local_inline`, `cluster`, or `scaffold_local` |
| **EXECUTE** | Run real tools in isolated processes | Exit status, stdout, stderr, and artifacts |
| **VALIDATE** | Check exit status and non-empty artifacts | Failed stages cannot enter the commit path |
| **C-1 GATE** | Revalidate four persistent evidence objects | Evidence bundle, successful-completion record, quorum pass, and completion proof |
| **SEAL** | Canonicalize, hash, synchronize, and append | Immutable, queryable committed facts |
| **RECOVER** | Replay validated events | Idempotent recovery without rerunning committed stages |

Event objects use restricted RFC 8785/JCS canonical JSON, domain-separated SHA-256 digests, and an append-only JSONL ledger. Writes use fsync ordering, and incomplete trailing records are isolated. “Deterministic recovery” specifically means **byte-for-byte reconstruction of workflow state from the same ledger**. It does not imply bitwise-identical bioinformatics results across operating systems, tool versions, or hardware platforms.

The C-1 gate requires all four evidence objects to bind to the committed run/cut/claim/contract. A non-zero exit status, empty artifact, or inconsistent evidence binding terminates the commit before sealing and prevents failed state from entering downstream processing.

### Relationship between 1.0 and 2.0

Version 2.0 does not rewrite the analysis scripts wholesale. It adds a durable control and execution layer over the 1.0 analytical capabilities. The 1.0 scripts remain independently callable; 2.0 incorporates them into recoverable stage graphs through `v1_adapter.py`.

| Dimension | 1.0 | 2.0 |
|---|---|---|
| State authority | Mutable `run_manifest.json` | Append-only, hash-chained event ledger |
| Crash recovery | Requires manual state assessment after interruption | Replays the ledger and remains idempotent over committed stages |
| Commit validation | No unified commit gate | C-1 four-evidence gate |
| Orchestration | Chained scripts | Drivable, recoverable DAG |
| Resource routing | None | Local execution, cluster script, or external scaffold |

The complete migration design is documented in [`docs/V1_V2_INTEGRATION.zh-CN.md`](docs/V1_V2_INTEGRATION.zh-CN.md).

### Boundary with other workflow systems

Snakemake and Nextflow provide more mature static DAGs, scheduler integration, and cluster-job lifecycle management. vivarium focuses on LLM-native goal interpretation, skill contracts, pre-commit evidence validation, and event-sourced state. These systems are not mutually exclusive: vivarium can generate auditable external commands or job scripts, but it does not currently submit or poll cluster jobs automatically.

For one ANI run, one BLAST search, or one figure, invoke the corresponding sub-skill directly. Prefer Snakemake or Nextflow when mature unattended cluster scheduling is required or when the workflow is entirely static and does not involve LLM-mediated orchestration.

## Skill index

| Skill | Core responsibility | Execution boundary |
|---|---|---|
| **`vivarium`** | Goal interpretation, stage-graph construction, and sub-skill orchestration | Complete workflows use the 2.0 event ledger as state authority by default |
| **`vivarium-prep`** | Assembly statistics, quality assessment, and annotation | Lightweight stages run locally; compute-intensive stages emit external commands |
| **`vivarium-compare`** | ANI/AAI, orthology, and synteny | FastANI, EzAAI, and MUMmer run when dependencies are available; OrthoFinder defaults to external execution |
| **`vivarium-phylo`** | Alignment, trimming, phylogeny, and codon-based selection analysis | Ordinary trees may run locally; large analyses and PAML may become external stages |
| **`vivarium-search`** | BLAST, DIAMOND, and HMMER search | Runs when tools and databases are available; otherwise returns explicit diagnostics |
| **`vivarium-report`** | Standardized figures, tables, and methods records | Exports editable SVG, PDF, and 600 dpi TIFF |

All six skills can be invoked independently or composed by the umbrella skill into an end-to-end stage graph.

## Benchmarks

### Skill effectiveness

Four task classes were compared with and without skills under identical prompts, inputs, and `bio_tools` environments. Complete inputs, raw outputs, and assertion-level evidence are available in [`benchmark/benchmark.md`](benchmark/benchmark.md).

| Metric | With skills | No-skill baseline | Difference |
|---|---:|---:|---:|
| Assertion pass rate | **100%** | 82% | **+18 percentage points** |
| Mean wall-clock time | **72 s** | 97 s | **approximately 26% faster** |
| Mean output tokens | 54.4 k | 53.2 k | +2% |

The principal differences concern delivery and reproducibility. The skill-enabled runs consistently record tool identity, version, and exact command, and export SVG, PDF, and 600 dpi TIFF. The no-skill baseline satisfied only 2/4 delivery assertions in the plotting task.

### Durability and memory consistency

The second benchmark used four real *Shewanella* genomes to compare the 2.0 durable loop with a no-skill baseline. The complete design, runtime telemetry, and independently recomputed evidence are available in [`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md).

| Metric | No-skill baseline | 2.0 durable loop |
|---|---:|---:|
| `memory_drift` | 1.00 | 1.00 |
| `output_hygiene` | 0.95 | **1.00** |
| Output tokens | 11,294 | **10,327** |
| Input tokens | 31,632 | 31,660 |
| `academic_completeness` | 0.95 | 0.95 |
| `correctness` | **1.00** | 0.98 |

Both configurations recited the key values accurately in this task. The distinction lies in the mechanism rather than the observed score: the baseline relies on model context, whereas the durable loop reads from sealed artifacts. The 0.02 `correctness` difference reflects unreported fastANI minimizer jitter, a reporting-completeness issue rather than an incorrect biological classification.

The data identify one same-species pair, *S. vesiculosa* M7 and PB002_L5, at approximately 98.5% ANI. The scoring prompt's expectation of no same-species pairing conflicts with the FASTA identifiers and the repository's existing analysis; the benchmark document records the supporting evidence.

> These metrics are limited to the recorded tasks, data, tool versions, model, and execution environment. They do not constitute a general performance ranking across models, hardware platforms, or workflow systems.

## Trigger contract

The six skills collectively provide **69** should-trigger and should-not-trigger queries. A further 20 adjacent-skill boundary queries currently show **20/20** agreement under manual review. This result evaluates trigger-rule consistency only and does not assess the scientific correctness of downstream bioinformatics analyses.

## Dependencies and implementation boundaries

The 2.0 durable kernel uses only the Python standard library and introduces no additional pip runtime dependencies. Analysis tools are resolved from the `bio_tools` conda environment and invoked only by their corresponding stages.

- **QC and annotation:** seqkit and Prokka; CheckM2, Flye, eggNOG-mapper, and dbCAN serve optional or compute-intensive stages.
- **Comparison:** FastANI, EzAAI, OrthoFinder, and MUMmer4.
- **Phylogenetics:** MAFFT, trimAl, IQ-TREE, FastTree, PAML, and PAL2NAL.
- **Search:** BLAST+, DIAMOND, and HMMER.
- **Plotting:** Python (pandas and matplotlib) or R (ggplot2, svglite, and ragg).

vivarium does not install software or databases automatically and does not modify the user's analysis environment. Missing dependencies produce explicit diagnostics and route the affected stage to external execution or a pending state.

Current implementation boundaries:

- Cluster-job script generation is implemented; automatic submission and polling are not.
- Resource routing is a conservative heuristic, not a precise runtime predictor.
- Cross-environment bitwise determinism remains sensitive to tool versions, random seeds, newline normalization, and graphics backends.
- “Publication-grade” refers to output formats, typesetting constraints, and provenance completeness; it does not assert that a scientific conclusion is ready for publication.
- Cleanup uses soft deletion by moving targets into `_deleted/`, preserving a recovery path.

## License

See [`LICENSE`](LICENSE) (MIT).
