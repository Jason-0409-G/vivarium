---
name: vivarium-search
description: >-
  Local sequence-similarity search for comparative genomics. Use whenever the user wants to find homologs of a gene or
  protein, BLAST or DIAMOND a query against a genome/proteome/CDS, check whether a genome or proteome carries a homolog
  of some sequence, identify what an unknown sequence is, find the best hit for a protein, or do an HMM/profile domain
  search (Pfam/dbCAN/TIGRFAM). Triggers on phrases like "blast this", "find homologs of", "search this protein against",
  "does this genome have a copy of", "what is this sequence", "best hit for", "搜一下这个序列/基因", "比对/BLAST 一下",
  "这个基因组有没有 X 的同源", "找同源", "鉴定这条序列", and any local protein/nucleotide similarity or domain search.
  Runs locally in the bio_tools conda env (blastp/blastn/tblastn/blastx, diamond, hmmer); returns a tidy named-column
  hit table, an interpretation, and a reproducible command. Part of the vivarium comparative-genomics skill set.
---

# vivarium-search — local sequence similarity search

Find what a sequence is, or where it occurs, by searching it against a target with BLAST, DIAMOND, or HMMER — and hand back a clean, thresholded hit table plus a short read of what the hits mean. This is the "what is this gene / does this proteome carry a homolog of X / which domains are in this protein" workhorse.

Everything runs locally in the `bio_tools` conda environment. Sequence search is light and fast, so this skill runs the search directly rather than handing back a command to run later — but it always records the exact command and tool version, because a hit table with no provenance is useless three months later when you write the methods.

## What the user should have at the end

1. A tidy TSV hit table with **named columns** (not raw outfmt-6 numbers nobody can read).
2. A short **interpretation**: how many hits pass threshold, the best hit(s), and any caveat (low coverage, borderline e-value, no hit).
3. One **provenance line**: tool + version + the exact command.

## Step 1 — read the task, pick the tool

Infer (or ask) three things: are the QUERY and TARGET protein or nucleotide; how big is the target; is the goal a homolog search or a domain/profile search. The wrong tool either wastes time or misses real hits, so choose deliberately:

| Goal | Query → Target | Tool | Why |
|---|---|---|---|
| Homolog search, protein, small/medium target | protein → protein | `blastp` | sensitive and exact; fine up to ~10⁵ sequences |
| Homolog search, protein, large target (>~10⁵ seqs) | protein → protein | `diamond blastp --sensitive` | ~100–1000× faster than blastp, comparable sensitivity for moderate divergence |
| Nucleotide vs nucleotide | nucl → nucl | `blastn` | |
| Protein query vs nucleotide target | protein → nucl | `tblastn` | translated search |
| Nucleotide query vs protein target | nucl → protein | `blastx` | translated search |
| Domain / family / profile membership | protein → HMM profile DB | `hmmscan` / `hmmsearch` | profiles beat pairwise search for remote or conserved domains; needs a profile DB (Pfam, dbCAN, TIGRFAM) |

If the target is a plain FASTA, a search database must be built first (`makeblastdb` / `diamond makedb`). The bundled script handles that for you. Note: in the bundled script the **diamond path is protein-vs-protein (blastp) only** — for cross-type searches use the BLAST `blastx`/`tblastn` tools (also via the script).

## Step 2 — run it (use the bundled script for BLAST/DIAMOND)

For the common protein and nucleotide BLAST/DIAMOND paths, call the bundled runner rather than hand-assembling flags. It checks the tool is present, builds the DB if needed, runs with sensible defaults, emits a **named-column TSV**, and prints the version + command:

```bash
bash <this-skill-dir>/scripts/vivarium_search.sh \
  --query  <query.fasta> \
  --target <target.fasta> \
  --type   prot|nucl \
  [--tool  auto|blastp|blastn|tblastn|blastx|diamond] \
  [--evalue 1e-5] \
  [--out   <hits.tsv>]
```

Call the script by its full path under this skill's directory — Claude's working directory is usually the user's project, not the skill folder, so a bare `scripts/...` will not resolve.

`--tool auto` (default) picks `blastp`/`blastn` from `--type`, and switches a protein search to `diamond blastp --sensitive` when the target has more than ~100k sequences. Default e-value `1e-5`; columns `qseqid sseqid pident length evalue bitscore qcovhsp`. `--type` drives the `auto` choice; if you pass `--tool` explicitly, set `--type` to match (the script sniffs the target alphabet and warns on an obvious mismatch). The script aborts before searching if a tool is missing or a search would be biologically meaningless (e.g. a protein DB requested over a nucleotide target).

Activate the env first (`conda activate bio_tools`) so the tools are on PATH. The script never auto-installs anything; if a tool is missing it tells you which one.

For **HMMER / profile** search the script doesn't cover it (profile DBs vary too much). Run `hmmscan`/`hmmsearch` directly against the user's profile DB with `--domtblout`, and record the command the same way.

## Step 3 — interpret, don't just dump the table

A wall of e-values is not an answer. Read the TSV and tell the user what it means:

- Count hits passing the threshold; name the **best hit** (subject, %identity, e-value, query coverage `qcovhsp`).
- Flag weak evidence rather than overstating it: e-value near the cutoff, query coverage below ~50%, or %identity in the twilight zone (below ~30% for proteins) is "possible homolog, verify" — not "it's X".
- If there are **zero hits**, say so plainly and suggest the next move: lower stringency, switch to a profile/HMM search for remote homology, or check that the query/target types and tool were right.

Report the signal, not 5000 rows. Surface the top hits; point to the full TSV for the rest.

## Step 4 — record provenance

Finish with one line the user can paste into a methods section: tool + version + the exact command. The bundled script prints this — carry it through verbatim. Reproducibility is nearly free here and expensive to reconstruct later.

## House rules (shared across vivarium)

- **Never auto-install** tools. If something is missing from `bio_tools`, name it and let the user decide.
- Don't `rm` intermediates; if cleanup is needed, move files to the project's `_deleted/`.
- Report facts; keep interpretation separate from the numbers and don't overstate a borderline hit.
