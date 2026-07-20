---
name: vivarium
description: >-
  Orchestrate an end-to-end comparative-genomics workflow over a genome set. Use for multi-stage or complete analyses
  such as "run the whole pipeline", "characterize these strains", "compare these genomes and make figures", "跑完整比较
  基因组流程", or requests naming vivarium 2.0, durable execution, the event ledger, crash recovery, or the full goal.
  Default new end-to-end work to the 2.0 durable plan/run engine; use the 1.0 mutable-manifest orchestrator only when the
  user explicitly requests legacy V1 behavior. For one isolated ANI, BLAST, tree, or figure, defer to the corresponding
  vivarium sub-skill.
---

# vivarium — durable comparative-genomics orchestrator

Coordinate multi-stage comparative-genomics analyses. For new end-to-end work, use the 2.0 event-sourced engine so the append-only ledger is the source of state authority. Run eligible stages locally; pause at scaffold or cluster stages and resume from the same ledger after outputs return.

This skill coordinates; analysis implementations live in the sub-skills. Read the relevant sub-skill before executing its stage.

| Sub-skill | Does |
|---|---|
| `vivarium-prep` | assembly QC (stats, CheckM2), annotation (Prokka → eggNOG/dbCAN) |
| `vivarium-compare` | ANI/AAI, orthology (OrthoFinder), synteny (MUMmer) |
| `vivarium-phylo` | alignment → trim → tree (IQ-TREE), selection (PAML dN/dS) |
| `vivarium-search` | BLAST/DIAMOND/HMMER sequence search |
| `vivarium-report` | standardized manuscript figures and tables (Python/R) |

## Select the execution mode

- **Route by scale, not by habit.** The durable kernel earns its token and artifact overhead only past a threshold. Drive it (`plan`/`run`, `full`) when the project is long-running, accumulates more state than fits one context window, must survive a crash, or needs an auditable commit chain or cluster routing. For a one-shot analysis that fits comfortably in context (a single ANI, one tree, one figure, or a short chain), run the stage(s) directly via the sub-skills — cheaper, with no correctness penalty. Benchmark basis: on a context-sized task the kernel added tokens (≈ +25–96% across tiers) with no correctness or memory-drift gain; its value appears only once project state exceeds carryable context (earliest-fact recall was 8% self-managed vs 100% via the ledger). See `benchmark/AUTHORITATIVE_VERDICT.zh-CN.md`.
- Use **V2 durable mode** for new complete/`full` workflows once the scale test above says the kernel is warranted, or whenever the request mentions `2.0`, `durable`, `event ledger`, `crash recovery`, or `C-1`.
- Use **V1 legacy mode only on explicit request**. Its `run_manifest.json` is a V1 coordination record, never the source of authority for a V2 run.
- Do not silently mix V1 and V2 state within one run.

## Map the goal

Map the request to one of the V2 goals:

- **compare-genomes** → prep:stats → compare:ani → compare:aai → report:heatmap
- **phylogeny** → prep:annotate(per genome) → compare:orthology(single-copy core) → phylo:tree → report
- **selection** → phylo:tree → phylo:selection(scaffold)
- **full** → prep(stats+annotate) → compare(ani+aai+orthology+synteny) → phylo:tree → report

Interpret “complete/full vivarium” as the **full** goal unless the user narrows the scope. The bundled full goal is the default genome-set workflow; it does not invent the query inputs required for arbitrary sequence searches or the orthogroup/codon inputs required for selection analysis. Add those only when the user supplies the required inputs or explicitly requests them.

## Plan before execution

From the repository root, print the device probe, routes, commands, dependencies, and expected artifacts:

```bash
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    plan --root <store_dir> --goal <goal> --genomes <genomes_dir>
```

Before running, summarize the ordered stages and identify `local_inline`, `cluster`, and `scaffold_local` boundaries. Never auto-install missing tools or auto-submit cluster jobs.

## Drive and resume the durable run

```bash
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    run --root <store_dir> --goal <goal> --genomes <genomes_dir>
```

Use `--goal full` for the complete default genome-set workflow. Re-run the same command after externally executed outputs are placed in the reported workspace; recovery must continue from the ledger without rerunning committed stages.

For every stage:

1. Preserve the planned dependency order and workspace.
2. Execute only stages routed `local_inline`.
3. At `cluster` or `scaffold_local`, stop and return the exact command, expected outputs, and destination workspace.
4. Admit outputs downstream only after validation and the C-1 evidence gate complete.
5. Build final claims and methods from committed artifacts and recorded provenance, not model memory.

## Legacy V1 mode

Only when the user explicitly requests V1 or legacy manifest behavior, use:

```bash
python3 <skill-dir>/scripts/orchestrate.py init \
    --goal <goal> --indir <genomes_dir> --workdir <dir>
```

Keep V1 outputs independently usable, but do not describe its mutable manifest as authoritative for a V2 run.

## House rules (shared across vivarium)

- **Never auto-install** tools or databases; surface what's missing and let the user decide.
- Do not permanently delete run workspaces or intermediates; use the repository's recoverable deletion policy.
- Keep interpretation tied to committed evidence; a generated figure alone does not establish a mechanism.
