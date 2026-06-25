---
name: vivarium-report
description: >-
  Make publication-grade figures (and tables / methods text) from comparative-genomics results, in Python OR R. Use
  whenever the user wants to plot or visualize genomics analysis output — an ANI/AAI heatmap, a CAZy/COG/KEGG category
  bar chart, a pangenome or presence/absence matrix, a dN/dS (ω) plot, a phylogenetic tree, a synteny/dot plot — or to
  turn analysis tables into a journal-ready figure, or draft a methods paragraph with tool versions. Triggers on phrases
  like "plot the ANI matrix", "make a heatmap of", "bar chart of CAZy/COG categories", "figure for the paper", "make this
  publication quality", "出个图", "画个热图/柱状图", "把这个表画成图", "出版级/Nature 风格的图", "ANI 热图". Produces
  editable SVG + PDF + TIFF (600 dpi) with Nature-style conventions (Arial, small fonts, editable text, restrained
  palette). This skill plots results that already exist — to *compute* ANI/AAI use vivarium-compare, to *build* a tree
  use vivarium-phylo, to *run* a search use vivarium-search; this one turns their output into the figure. Part of the
  vivarium comparative-genomics skill set. NOT for interactive/web plots (plotly) or Illustrator-first layout.
---

# vivarium-report — publication-grade figures from comparative-genomics results

Turn an analysis table (an ANI matrix, a CAZy/COG count table, a dN/dS summary, a tree) into a figure that defends a claim and survives review — not a pretty plot in isolation. Figures come out journal-ready: Arial, small fonts, editable text, a restrained palette, exported as **SVG (editable) + PDF + TIFF (600 dpi)**.

## Step 0 — figure contract, before any code

State these four things first; they decide the plot, not the aesthetics:
1. **Claim**: the one sentence this figure must defend (e.g. "L5 and M7 are conspecific, >95% ANI").
2. **Figure type / data**: which analysis output feeds it (table below).
3. **Backend**: **Python or R?** This is a blocking choice — if the user has not said which, ask "Python or R?" and stop. Both are bundled; use the chosen one exclusively (don't render an R figure with Python or vice-versa).
4. **Export**: final size + formats. Default SVG + PDF + TIFF (600 dpi), editable text.

## Step 1 — map the result to a figure type

| Result (vivarium output) | Figure | Bundled? |
|---|---|---|
| ANI / AAI matrix (square TSV) | annotated heatmap | ✅ `heatmap` |
| CAZy / COG / KEGG category counts per genome (TSV) | grouped or stacked bars | ✅ `bars` |
| Gene-family presence/absence, small matrix | heatmap (0/1) | ✅ `heatmap` |
| dN/dS (ω) per orthogroup | lollipop / sorted bars | use `bars` (one series) or draw directly |
| Phylogenetic tree (Newick + support) | tree | not bundled → R `ggtree`/`treeio`, or Python `Bio.Phylo`/`ete3` |
| Synteny (MUMmer coords) | dot/alignment plot | not bundled → draw directly (matplotlib / `genoPlotR`) |

The two most reused, table-driven figures — **heatmap** and **bars** — are bundled and styled. Trees and synteny need their own libraries; draw them directly in the chosen backend, keeping the same styling (below).

## Step 2 — run the bundled plotter (chosen backend)

Both backends bake in the publication style and write SVG + PDF + TIFF (600 dpi). Call the script under this skill's directory with its full path (Claude's cwd is usually the user's project).

**Python** (matplotlib/seaborn):
```bash
python <skill-dir>/scripts/plot.py heatmap --input ANI_matrix.tsv --out fig_ani \
    --annot --vmin 95 --vmax 100 --cmap viridis --cbar-label "ANI (%)" --title "Genome-wide ANI"
python <skill-dir>/scripts/plot.py bars --input cazy_counts.tsv --out fig_cazy \
    --ylabel "CAZymes" --title "CAZy families per genome"        # add --stacked for stacked
```

**R** (ggplot2):
```bash
Rscript <skill-dir>/scripts/plot.R heatmap --input ANI_matrix.tsv --out fig_ani \
    --annot --vmin 95 --vmax 100 --cbar-label "ANI (%)" --title "Genome-wide ANI"
Rscript <skill-dir>/scripts/plot.R bars --input cazy_counts.tsv --out fig_cazy \
    --ylabel "CAZymes" --title "CAZy families per genome"        # add --stacked
```

Input conventions: **heatmap** = a TSV/CSV with row labels in column 1 and a numeric square (or rectangular) matrix. **bars** = a TSV/CSV with the category in column 1 and one numeric column per genome/sample. Both backends auto-detect the delimiter (tab/comma), preserve column order, set `--vmin/--vmax` to focus the colour scale, and write the same three formats. One portability note: the R PDF embeds fonts via `cairo_pdf` when available, otherwise falls back to base-14 Helvetica (renders identically everywhere but is technically non-embedded — the script prints a note); the Python PDF always embeds. TIFFs are LZW-compressed.

If the chosen backend's runtime or a required package is missing (R: `ggplot2`, ideally `svglite`/`ragg`; Python: `pandas`/`matplotlib`), the script stops and names the missing piece. **Do not auto-install** and **do not fall back to the other backend** to substitute a figure — report the blocker and give the install command.

## Step 3 — read the figure like a reviewer

Before handing it over, check it carries the claim, not just data:
- Does the **hero comparison** read at a glance (e.g. the diagonal/off-diagonal split in an ANI heatmap)? Pick `--vmin/--vmax` so the meaningful range fills the colour scale instead of being washed out by a 0–100 default.
- One restrained palette; direct labels over legends where categories are few and fixed; white background.
- Are `n`, units, and the scale labelled? A heatmap without a colour-bar label or bars without a y-unit is not finished.
- Keep the source table next to the figure (traceability) and note tool versions if this feeds a methods section.

## Step 4 — methods-ready provenance (optional)

If the figure is for a manuscript, draft a one- or two-sentence methods note recording the tool + version that produced the underlying numbers (carry it from the upstream vivarium run manifest), plus the plotting backend. Reproducibility is part of the figure.

## House rules (shared across vivarium)

- **Never auto-install** packages or fonts; name what's missing and let the user decide.
- Don't `rm` outputs; if cleanup is needed, move files to the project's `_deleted/`.
- The figure serves the scientific logic — aesthetic polish is subordinate to making the claim clear and reviewable. Don't overstate: a heatmap shows similarity, it doesn't prove a mechanism.
