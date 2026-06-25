# vivarium

> A Claude Code skill set for local comparative genomics. ｜ 面向本地比较基因组学的 Claude Code 技能集。
> **English** below · **中文**见下半部分（[跳转](#中文)）

---

## Overview

**vivarium** is a Claude Code skill set for conducting comparative-genomics analyses locally. Given a set of genome assemblies and an analysis goal, it plans the analysis as a stage graph, executes the lightweight steps in a `bio_tools` conda environment, and returns publication-grade figures and tables together with methods-ready provenance. The skill set adopts a **hybrid-execution** model: lightweight analyses (assembly QC, ANI/AAI, alignment-to-tree, sequence search, plotting) are run immediately, whereas computationally intensive or long-running stages (de novo assembly, eggNOG/dbCAN functional annotation, OrthoFinder orthology, large phylogenies, PAML selection tests) are emitted as ready-to-run commands for the user to execute, with their outputs ingested and interpreted on return.

vivarium is the analytical counterpart of the manuscript-preparation skill set [`scriptorium`](https://github.com/Jason-0409-G/scriptorium) (research-to-paper): scriptorium converts research into manuscripts; vivarium converts genomes into results.

## Skills

| Skill | Function | Local / scaffolded |
|---|---|---|
| **`vivarium`** | Umbrella orchestrator: goal → analysis DAG → sub-skill chaining → `run_manifest` tracking → pause/resume at heavy stages | coordinates |
| **`vivarium-prep`** | Assembly QC (contigs / N50 / GC / completeness); annotation (Prokka → eggNOG / dbCAN) | `stats` local; assembly / eggNOG / dbCAN scaffolded |
| **`vivarium-compare`** | Genome relatedness (ANI/AAI via FastANI/EzAAI); orthology (OrthoFinder); synteny (MUMmer) | ANI / AAI / synteny local; OrthoFinder scaffolded |
| **`vivarium-phylo`** | Align → trim → infer tree (MAFFT / trimAl / IQ-TREE); selection (PAML dN/dS) | `tree` local; PAML scaffolded |
| **`vivarium-search`** | Sequence-similarity search (BLAST / DIAMOND / HMMER) | local |
| **`vivarium-report`** | Publication-grade figures and tables (Python matplotlib / R ggplot2); export to SVG + PDF + TIFF at 600 dpi | local |

Each skill is independently triggerable; the umbrella `vivarium` composes them into an end-to-end pipeline.

## Benchmark (with-skill vs. no-skill baseline)

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

**Interpretation.** The skill set matches a careful baseline on biological correctness but diverges where publishability and reproducibility are at stake: (i) every run records a `tool + version + command` provenance footer, which an unguided run logs inconsistently; (ii) "publication-grade" output is consistently editable SVG + PDF + 600 dpi TIFF in a restrained, Nature-style convention, whereas the baseline produced a screen-resolution raster; (iii) the deliverables directory contains only results, scratch databases being confined to temporary directories; and (iv) invoking hardened bundled scripts rather than re-deriving command-line flags reduces wall-clock time by ≈26%.

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

## Dependencies

Analysis tools must be available in a **`bio_tools` conda environment** (the skills never auto-install; missing tools are reported, not installed):
- QC / annotation: seqkit, Prokka, (CheckM2, Flye, eggNOG-mapper, dbCAN — optional / heavy)
- Comparison: FastANI, EzAAI, OrthoFinder, MUMmer4
- Phylogenetics: MAFFT, trimAl, IQ-TREE, FastTree, PAML (codeml), PAL2NAL
- Search: BLAST+, DIAMOND, HMMER
- Plotting: Python (pandas / matplotlib) or R (ggplot2 / svglite / ragg)

## Design principles

- **Hybrid execution.** Lightweight steps run immediately; heavy steps are emitted as commands for the user to run — no unattended long jobs.
- **No automatic installation.** Missing tools or databases are surfaced for the user to decide upon.
- **Provenance (software versions recorded at every step).** Each script prints a uniform footer `=== vivarium-… done === / tool: <name>(<version>) / command: <exact command>`; the six analysis scripts and both plotting back-ends (matplotlib / ggplot2, with their versions) are unified, so output is methods-ready.
- **Figures serve the science.** No overstatement; an n = 1 observation is not extrapolated.
- **Soft deletion.** No `rm`; files requiring removal are moved to `_deleted/`.
- **Robust under weaker, non-Claude models.** Every step is "run this exact command and read its output"; analytical logic lives entirely in bundled scripts (FastANI / IQ-TREE / BLAST … plus the unified provenance footer), so the model neither assembles flags nor orchestrates multi-step tool calls. The set therefore remains stable on a non-Claude backend (e.g. `deepseek-v4-pro[1m]`, sub-agents on `deepseek-v4-flash`).

## License

See `LICENSE` (MIT).

---

<a id="中文"></a>
# vivarium（中文）

> 面向本地比较基因组学的 Claude Code 技能集。

## 概述

**vivarium** 是一套用于在本地开展比较基因组学分析的 Claude Code 技能集。给定一组基因组序列与一个分析目标，它将分析规划为阶段图（DAG），在 `bio_tools` conda 环境中执行轻量步骤，并产出可发表级的图与表，同时附带可直接写入方法学的溯源记录。技能集采用**混合执行**模式：轻量分析（组装质控、ANI/AAI、比对建树、序列搜索、绘图）即时运行；而计算密集或耗时的阶段（从头组装、eggNOG/dbCAN 功能注释、OrthoFinder 直系同源、大规模系统发育、PAML 选择压检验）则生成可直接执行的命令交由用户运行，结果返回后再由技能解读。

vivarium 与论文写作技能集 [`scriptorium`](https://github.com/Jason-0409-G/scriptorium)（research-to-paper）互为配套：scriptorium 将研究写成论文，vivarium 将基因组跑成结果。

## 技能

| 技能 | 功能 | 本地运行 / 生成命令 |
|---|---|---|
| **`vivarium`** | 伞型协调器：目标 → 分析 DAG → 串联各子技能 → `run_manifest` 追踪 → 重活阶段暂停/续跑 | 协调 |
| **`vivarium-prep`** | 组装质控（contigs / N50 / GC / 完整度）；注释（Prokka → eggNOG / dbCAN） | `stats` 本地运行；组装 / eggNOG / dbCAN 生成命令 |
| **`vivarium-compare`** | 基因组亲缘度（FastANI/EzAAI 的 ANI/AAI）；直系同源（OrthoFinder）；共线性（MUMmer） | ANI / AAI / synteny 本地运行；OrthoFinder 生成命令 |
| **`vivarium-phylo`** | 比对 → 修剪 → 建树（MAFFT / trimAl / IQ-TREE）；选择压（PAML dN/dS） | `tree` 本地运行；PAML 生成命令 |
| **`vivarium-search`** | 序列相似性搜索（BLAST / DIAMOND / HMMER） | 本地运行 |
| **`vivarium-report`** | 可发表级图与表（Python matplotlib / R ggplot2）；导出 SVG + PDF + TIFF（600 dpi） | 本地运行 |

各技能均可独立触发，亦可由伞型 `vivarium` 串联为端到端流程。

## 性能基准（带技能 vs 无技能基线）

在四个代表性任务（搜索 / 比较 / 系统发育 / 出图）上进行评测，使用同一套 prompt 与同一个 `bio_tools` 环境，以「是否提供该技能」为唯一变量。任务由 claude-opus-4-8（general-purpose 子代理）执行，每种配置各一次（单机单跑，属方向性证据而非统计功效结论）。完整数据与逐条断言证据见 [`benchmark/benchmark.md`](benchmark/benchmark.md)。

| 指标 | 带技能 | 无技能基线 | 差值 |
|---|---|---|---|
| **断言通过率** | **100%** | 82% | **+18 个百分点** |
| **墙钟时间（均值）** | **72 s** | 97 s | **快约 26%** |
| 输出 token（均值） | 54.4 k | 53.2 k | +2%（读取 SKILL.md 的一次性成本） |

| 任务 | 通过（技能） | 通过（基线） | 技能的差异所在 |
|---|---|---|---|
| 搜索 · 3 条 query 找同源 | 5/5 | 4/5 | 基线将 8 个 BLAST 库二进制文件遗留在交付目录；技能在临时目录建库 |
| 比较 · 4 基因组 ANI + 同种判定 | 4/4 | 4/4 | 正确性持平；技能快约 37%，矩阵干净、无日志残留 |
| 系统发育 · 8 条 groEL ML 树 | 4/4 | 4/4 | 持平；两者均正确报告该树不可分辨（序列近乎同一），未过度宣称 |
| 出图 · 可发表级 ANI 热图 | 4/4 | **2/4** | 基线仅导出屏幕分辨率 PNG、无 600 dpi TIFF；技能恒定导出 SVG + PDF + TIFF（600 dpi，LZW） |

**解读。** 技能集在生物学正确性上与认真的基线持平，但在「可发表 / 可复现」处显现差异：① 每次运行均记录 `工具 + 版本 + 命令` 溯源脚注，而裸跑记录不一致；② 「可发表级」输出恒为可编辑的 SVG + PDF + 600 dpi TIFF，遵循克制的 Nature 风格，基线则给出屏幕分辨率栅格图；③ 交付目录仅保留结果，临时数据库限于临时目录；④ 调用经打磨的捆绑脚本而非重新推导命令行参数，使墙钟时间缩短约 26%。

## 触发命中率

在一组刻意设置边界难度的 20 条路由查询上——包括「渲染一棵**已有**的树」（应走 report 而非 phylo）、「ANI 已算好、画成图」（应走 report 而非 compare）、整流程 vs 单步请求，以及四条「不应触发任何技能」的负样本（撰写方法、润色摘要、天气、总结 PDF）——六个技能描述全部路由正确（**20/20 = 100%**）。每个技能另附 `evals/trigger_evals.json`（共 67 条 should-/should-not-trigger 查询），既作为触发契约，又作为回归护栏；配置 API key 后，可经 `run_loop.py --eval-set <file>` 直接喂入官方 `skill-creator` 优化器。

## 安装

**方式一 · 插件市场（推荐）**
```
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git
/plugin install vivarium@vivarium
/reload-plugins
```
> 使用完整 HTTPS 网址，避免无 SSH 密钥时克隆失败。

**方式二 · 脚本（克隆后本地安装）**
```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh            # 将 skills/ 拷入 ~/.claude/skills/
```

## 依赖

分析工具需位于 **`bio_tools` conda 环境**（技能从不自动安装；缺失只提示、不安装）：
- 质控 / 注释：seqkit、Prokka、（CheckM2、Flye、eggNOG-mapper、dbCAN —— 可选 / 重活）
- 比较：FastANI、EzAAI、OrthoFinder、MUMmer4
- 系统发育：MAFFT、trimAl、IQ-TREE、FastTree、PAML（codeml）、PAL2NAL
- 搜索：BLAST+、DIAMOND、HMMER
- 出图：Python（pandas / matplotlib）或 R（ggplot2 / svglite / ragg）

## 设计原则

- **混合执行**：轻量步骤即时运行，重活生成命令交由用户运行，绝不无人值守地跑长任务。
- **绝不自动安装**：缺失的工具或数据库仅提示，由用户决定。
- **溯源（每步记录软件版本号）**：每个脚本运行后打印统一脚注 `=== vivarium-… done === / tool: <名>(<版本>) / command: <精确命令>`；六个分析脚本与两个出图后端（matplotlib / ggplot2，含各自版本）已全部统一，输出可直接写入方法学。
- **图服务于科学逻辑**：不过度宣称，n = 1 不外推。
- **软删除**：不使用 `rm`，需清理的文件移入 `_deleted/`。
- **对较弱的非 Claude 模型稳健**：每一步均为「运行这条确定命令并读取其输出」；分析逻辑全部位于捆绑脚本中（FastANI / IQ-TREE / BLAST … 及统一溯源脚注），模型既不需自行拼装参数，也不需编排多步工具调用，因而在非 Claude 后端（如 `deepseek-v4-pro[1m]`，子代理使用 `deepseek-v4-flash`）上同样稳定。

## 许可

见 `LICENSE`（MIT）。
