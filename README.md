# vivarium

<p align="center">
  <a href="docs/media/vivarium-v2-durable-loop-4k.png">
    <img src="docs/media/vivarium-v2-durable-loop-4k.png" alt="Vivarium 2.0 事件溯源、崩溃安全与证据闸门机制图" width="100%">
  </a>
</p>

> [English](README.en.md) ｜ **中文**
>
> **比较基因组学的持久化分析执行内核**——流程建模为事件溯源的状态机，每个数值都可溯源到已密封的提交事实，进程在任意点崩溃后可按字节确定性恢复。以 Claude Code 插件、Codex skills 与纯标准库内核交付（非集群调度器）。

LLM 驱动的比较基因组学分析有两处静默失效。其一，流程跑了一小时被中断，用可变清单记录的状态写坏，已算出的数值不再可信；其二，上下文随阶段增长，模型在任务末端"凭记忆"复述一个不再对应任何真实计算的数值。vivarium 2.0 把流程状态放进**仅追加、哈希链的事件账本**：崩溃后自账本按字节确定性重建，末端复述**从已提交产物读回而非凭回忆**——账本即记忆。

**面向：** 需要方法学级溯源与可复现性的 PI；要在本机与集群间跑长流程、且要求中断后确定性恢复的生信工程师；想要可发表级图表的实验生物学家。

**配套：** vivarium 与论文写作技能集 [`scriptorium`](https://github.com/Jason-0409-G/scriptorium)（research-to-paper）互为搭档——scriptorium 将研究整理为论文，vivarium 将基因组转化为结果。

---

## 项目状态

| 项目 | 当前状态 |
|---|---|
| **维护状态** | **持续维护与迭代**；后续版本将依据真实数据基准、跨端兼容性验证和用户反馈增量发布 |
| **当前版本线** | `v2.0.0`；2.0 为当前主线，1.0 分析脚本继续保持独立可用 |
| **支持端** | Claude Code 插件与 Codex skills；两端共享同一组 `SKILL.md` 工作流契约 |
| **版本记录** | 语义化版本号、[`CHANGELOG.md`](CHANGELOG.md) 与 [GitHub Releases](https://github.com/Jason-0409-G/vivarium/releases) |
| **开发路线** | 公开任务、验收标准、依赖、风险和阶段状态见 [`docs/VIVARIUM_V2_TASKS.zh-CN.md`](docs/VIVARIUM_V2_TASKS.zh-CN.md) |

> 持续更新不等于隐藏实验性边界。尚未完成的能力会在路线图和发布说明中明确标记；其中，集群作业自动提交与轮询仍属于后续版本范围。

## 安装

### Claude Code

推荐通过插件市场安装，以便统一管理版本与更新。以下命令依次注册市场、安装插件并重新加载当前会话：

**方式一 · 插件市场（推荐）**
```
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git
/plugin install vivarium@vivarium
/reload-plugins
```
> 使用完整 HTTPS 地址可避免安装过程依赖本机 SSH 凭据。

如需审阅源码或固定本地副本，可克隆仓库后运行安装脚本：

**方式二 · 脚本（本地安装）**
```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh            # 将 skills/ 拷入 ~/.claude/skills/
```

### Codex

`$skill-installer` 将技能安装到 `$CODEX_HOME/skills`（默认 `~/.codex/skills`）。如采用手工安装，Codex 也可从用户级 `$HOME/.agents/skills` 或仓库级 `.agents/skills` 发现技能，并支持符号链接。安装本仓库时必须同时注册伞型技能及五个子技能。

**方式一 · `$skill-installer`（推荐）**

将以下请求粘贴到 Codex：

```text
Use $skill-installer to install these paths from repo Jason-0409-G/vivarium using --ref master:
skills/vivarium
skills/vivarium-prep
skills/vivarium-compare
skills/vivarium-phylo
skills/vivarium-search
skills/vivarium-report
```

> 本仓库默认分支为 `master`，而 `$skill-installer` 的默认 `--ref` 是 `main`；因此不得省略 `--ref master`，否则下载阶段会失败。

新安装的技能通常在下一轮任务中自动可用；若技能列表未刷新，请重启 Codex。

**方式二 · 本地克隆并建立用户级符号链接**

```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
mkdir -p "$HOME/.agents/skills"
for skill in vivarium vivarium-prep vivarium-compare vivarium-phylo vivarium-search vivarium-report; do
    ln -s "$PWD/skills/$skill" "$HOME/.agents/skills/$skill"
done
```

该方式保留单一源码副本，后续 `git pull` 即可使 Codex 读取更新后的技能内容。仅希望在当前仓库启用时，可将链接建立在仓库根目录的 `.agents/skills` 中。详见 [Codex 技能说明](https://learn.chatgpt.com/docs/build-skills)。

## 更新

发布版本由 `.claude-plugin/plugin.json` 中的 `version` 字段标识，并遵循语义化版本约定；版本变更记录以根目录 [`CHANGELOG.md`](CHANGELOG.md) 为准。

### Claude Code

插件市场安装需先刷新市场索引，再安装最新版本并重新加载会话：

**插件市场安装**
```
/plugin marketplace update vivarium     # 拉取最新目录
/plugin update vivarium@vivarium        # 安装新版本
/reload-plugins                         # 本会话即时生效（或重启）
```
也可在 `/plugin` → Marketplaces 中为 `vivarium` 启用 **auto-update**。自动更新仍以市场索引和插件版本号为判定依据。

本地脚本安装不会自动同步仓库；更新时需显式拉取代码并重新执行安装脚本：

**脚本安装**
```bash
cd vivarium   # 先前克隆的目录
git pull
bash install.sh
```

### Codex

采用本地克隆与符号链接安装时，链接目标保持不变，只需更新源码：

```bash
cd vivarium
git pull
```

Codex 通常会自动检测技能文件变化；若当前会话仍显示旧版本，请重启 Codex。通过 `$skill-installer` 安装的独立副本应按相同的六个技能路径并显式指定 `--ref master` 重新同步；需要持续跟踪仓库更新时，建议使用本地克隆与符号链接方式。

## 为什么用 vivarium（而不是直接跑脚本）

三条价值主张，各对应一类采用者，每条均由代码或基准支撑：

- **可复现到方法学（面向 PI）。** 每一步落地统一溯源脚注 `工具 + 版本 + 精确命令`，六个分析脚本与两个出图后端已统一；无引导的裸跑记录不一致（基准一，[`benchmark/benchmark.md`](benchmark/benchmark.md)）。
- **崩溃安全的长流程（面向生信工程师）。** 状态置于仅追加事件账本，中断后按字节确定性重建、对已提交阶段幂等不重跑；据设备核数/内存/调度器在本机与集群间路由（内核 `loop.py` / `pipeline.py`）。
- **可发表级交付（面向实验生物学家）。** 恒定导出可编辑 SVG + PDF + TIFF（600 dpi，LZW）；无引导基线仅产屏幕分辨率 PNG（基准一出图任务 4/4 vs 2/4）。

**何时不必用内核。** 只想跑单步（一次 BLAST、一张热图、一次 ANI）时，直接触发对应子技能即可，无需驱动内核。需要成熟的集群作业自动提交与轮询、或不涉及 LLM 编排的纯静态流水线时，应使用 Snakemake / Nextflow——vivarium 生成可提交的 sbatch/qsub 脚本但**不自动提交**（见"资源感知路由"一节）。

## 只有 vivarium 2.0 做的

将分散于各处的差异点汇为一处，每条注明其代码出处：

1. **事件溯源账本作为唯一权威来源**——状态不可变、哈希链，崩溃后按字节确定性重建（`ledger.py` fsync + 撕裂尾隔离；`canonical.py` 域分隔 SHA-256）。
2. **C-1 四证据提交闸门**——阶段进入 COMMITTED 前重新校验四个持久化证据对象并绑定已提交 run/cut/claim/contract；空产物或非零退出码在入账前被拦截（`loop.py` 提交前 fail-closed；`project.py` 提交时四证据复核）。
3. **记忆漂移作为一等可测指标**——复述即读回已密封产物，正确性与上下文长度无关（基准二，[`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md)）。
4. **一条可驱动、可恢复的 DAG 上做资源感知本地/集群路由**——`local_inline` / `cluster` / `scaffold_local` 三路由（`pipeline.py`）。

## 与其他方案的定位

诚实对照：Snakemake / Nextflow 在成熟的 DAG 与集群作业提交上更强（这是 vivarium 明确留待后续之处），此处不作宣称；vivarium 2.0 的独特之处在于**账本即唯一权威来源 + 提交前四证据校验 + 消除记忆漂移 + LLM 原生的目标→DAG 编排**——这些是其他方案都不提供的。

| 维度 | 手写脚本 | 可变清单流程<br>（含 vivarium 1.0） | Snakemake / Nextflow | 通用 Agent skill | **vivarium 2.0** |
|---|---|---|---|---|---|
| 崩溃后确定性恢复 | 无 | 无（清单可静默损坏） | 部分（重跑规则） | 无 | **有（自账本按字节重建）** |
| 提交前证据校验 | 无 | 无 | 无 | 无 | **C-1 四证据闸门（空产物/非零退出拦截）** |
| 状态权威来源 | 无载体 | 可变文件（可就地改写） | 文件时间戳/DAG | 模型上下文 | **不可变哈希链账本** |
| 复述=读回已提交事实 | 靠人记 | 靠回忆 | 不适用 | 靠上下文回忆 | **读回不可变已密封产物** |
| 记忆漂移 | 未测量 | 未测量 | 不适用 | 未测量 | **一等可测指标** |
| LLM 原生 目标→DAG 编排 | 无 | 无 | 无 | 部分 | **有** |
| 资源感知本地/集群路由 | 无 | 无 | 有（成熟） | 无 | **有（生成脚本；自动提交留待后续）** |

## 1.0 → 2.0：变了什么

2.0 唯一改动的是**执行层的状态权威来源**：把 1.0 的可变 JSON 清单（`run_manifest.json`）替换为仅追加事件账本。1.0 的全部分析脚本保持独立可用，2.0 通过一层通用适配器（`v1_adapter.py`）将其作为持久化阶段驱动，默认行为不变。

| 维度 | 1.0 | 2.0 durable loop |
|---|---|---|
| 状态载体 | 可变 JSON 清单（`run_manifest.json`），中断/截断/跨阶段失真可致静默损坏 | 仅追加事件账本；文件先于目录的 fsync 定序，撕裂尾部隔离 |
| 崩溃安全 | 无——进程中断即状态不可信 | 有——任意点中断后自账本按字节确定性重建，对已提交阶段幂等不重跑 |
| 权威来源 | 可变清单（可被就地改写） | 事件溯源账本（不可变、哈希链）——**故复述=读回，无记忆漂移** |
| 提交校验 | 无提交闸门 | C-1 四证据闸门，空产物/非零退出在提交前拦截 |
| 资源感知 | 无 | `probe_device()` + `route_stage()`：`local_inline` / `cluster`（生成 sbatch/qsub）/ `scaffold_local` 三路由 |
| 编排形态 | 脚本串联 | 单一可驱动、可恢复的 DAG（`plan`/`run` 展开阶段图，就地阶段自动跑、重活阶段暂停续跑） |
| 记忆漂移 | **未测量** | 作为一等指标测量（recall-vs-computed 一致性），本基准两配置均 1.0 |

关键迁移是**权威来源**：1.0 的可变清单既可能静默损坏，也无法为"复述即读回不可变事实"提供支撑；2.0 将状态置于哈希链账本后，"记忆"从模型上下文迁移到磁盘上的已密封证据——这正是 2.0 能把记忆漂移作为可测量指标的前提。融合细节见 [`docs/V1_V2_INTEGRATION.zh-CN.md`](docs/V1_V2_INTEGRATION.zh-CN.md)。

## 2.0 持久化执行内核

2.0 将比较基因组学流程建模为一台**事件溯源的状态机**。每个机制先陈述**保证**，再给出**机制**；术语保留其精确名义。

**保证：任意点崩溃后状态可按字节确定性重建，已完成阶段不重算。**
机制——每一阶段的执行产物经受限 RFC-8785/JCS 规范化 JSON 编码（禁用浮点，以规范十进制字符串表达）、域分隔 SHA-256 摘要后，追加写入仅追加的 JSONL 账本；写入遵循文件先于目录的 fsync 定序，并对撕裂尾部（写到一半的尾行）进行隔离而非误读。进程在任意点中断后，系统可自账本按字节确定性重建流程状态，且对已提交阶段幂等。

**保证：失败或空产物永不进入账本污染下游。**
机制——一个阶段进入 COMMITTED 之前，必须对四个持久化证据对象——证据包（evidence bundle）、成功完成记录、法定通过裁决（quorum pass）、完成证明（completion proof）——重新校验，且四者均须绑定到已提交的 run/cut/claim/contract。空产物或非零退出码在**任何证据对象被密封之前**即被拦截（`loop.py` 的验证硬闸门先于封章执行），因而不会留下半写的提交意图污染恢复。

**保证：据你的机器判断每一阶段在本机跑还是上集群。**
机制——`probe_device()` 探测本机核数、物理内存与集群调度器（sbatch/qsub/bsub）的存在性；`route_stage()` 据此为每一阶段判定执行位置：
- `local_inline`——所需工具已安装且资源可容纳，就地执行并提交；
- `cluster`——阶段计算量超出本机容量但存在调度器，生成可直接提交的 sbatch/qsub 作业脚本；
- `scaffold_local`——工具缺失或资源不足且无调度器，生成命令交由用户外部执行，产物经回收后校验入账。

> **诚实边界。** 该路由为资源感知的**启发式**判定（对超出容量的阶段保守拦截），并非精确耗时预测；作业脚本生成已实现，集群作业的**自动提交与轮询留待后续版本**。

**保证：一条可驱动、可恢复的 DAG。**
机制——`vivarium v2 plan/run` 将四个目标（`compare-genomes` / `phylogeny` / `selection` / `full`）展开为有序阶段图，每一阶段携带确切命令、期望产物、依赖边与路由决策。驱动过程自动执行就地阶段，在首个需人工介入或需集群提交的阶段暂停并预建工作目录；用户回收产物后再次驱动，流程自持久账本恢复并续跑。

```bash
# 打印设备探测结果、逐阶段路由决策、确切命令与期望产物
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    plan --root ./store --goal compare-genomes --genomes ./genomes

# 驱动流程：就地阶段自动执行并提交，scaffold/cluster 阶段暂停待人工
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    run  --root ./store --goal compare-genomes --genomes ./genomes
```

**一次运行长什么样。** 以基准二的真实运行为例（四个真实 *Shewanella* 基因组，见 [`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md)）：`plan` 将 `compare-genomes` 展开为四阶段并标注每阶段路由 → `run` 就地跑 `00-prep-stats` 与 `01-compare-ani`（真 FastANI）并密封提交 → 在 `02-compare-aai` 处暂停（EzAAI 缺失，符合设计，非本任务所需）→ 续跑 `03-report-heatmap` 产出已提交的 600 dpi ANI 热图（SVG + PDF）。共三阶段封章入账，判出恰好 1 个同种对（*S. vesiculosa* M7 + PB002_L5，ANI ≈ 98.5%），每步附 `工具 + 版本 + 命令` 溯源。

> 伞型 `vivarium` 技能以运行清单作为**协调层**追踪各子技能；`plan/run` CLI 是其下的**持久化执行层**——事件账本是 2.0 流程状态的权威来源。

## 技能

| 技能 | 核心职责 | 执行模式与边界 |
|---|---|---|
| **`vivarium`** | 伞型协调层：目标解析 → 阶段图构建 → 子技能编排 → 阶段暂停与续接 | 负责协调，不直接实施分析；需要持久化执行时，由 2.0 内核以事件账本承担状态权威 |
| **`vivarium-prep`** | 组装统计与质量评估；基因及功能注释 | `stats` 与 Prokka 在依赖满足时就地执行；CheckM2、Flye、eggNOG 和 dbCAN 生成可审计的外部执行命令 |
| **`vivarium-compare`** | ANI/AAI、直系同源关系及基因组共线性分析 | FastANI、EzAAI 和 MUMmer 在依赖满足时就地执行；OrthoFinder 默认作为外部计算阶段 |
| **`vivarium-phylo`** | 序列比对、修剪、最大似然建树及基于密码子的选择分析 | 常规规模建树可就地执行；大规模或分区建树及 PAML 分析生成外部执行命令 |
| **`vivarium-search`** | 基于 BLAST、DIAMOND 或 HMMER 的序列相似性与谱模型检索 | 工具及数据库可用时就地执行；依赖缺失时停止并返回明确诊断 |
| **`vivarium-report`** | 将已验证分析结果转换为标准化论文图件 | 内置支持 heatmap 与 bars；树图和共线性图由指定后端绘制；导出 SVG、PDF 与 600 dpi TIFF |

六项技能既可独立调用，也可由伞型 `vivarium` 编排为阶段图。需要崩溃恢复、提交前验证与可重放状态时，流程由 2.0 持久化内核驱动。阶段的实际执行位置由依赖可用性、资源需求和路由结果共同决定：满足条件的阶段就地执行；计算密集或依赖专用环境的阶段生成可审计命令与预期产物契约，返回产物经验证后方可进入下游流程。

## 基准评测

### 一、技能有效性基准（带技能 vs 无技能基线）

在搜索、比较、系统发育和出图四类代表性任务上，采用相同 prompt、相同输入数据与相同 `bio_tools` 环境，并以是否加载技能作为唯一配置差异。任务由 claude-opus-4-8（general-purpose 子代理）执行，结果依据预定义断言逐项复核。该评测用于比较既定任务与执行配置下的结果正确性、运行耗时和交付规范；完整输入、环境记录、原始输出与逐条评分证据见 [`benchmark/benchmark.md`](benchmark/benchmark.md)。

| 指标 | 带技能 | 无技能基线 | 差值 |
|---|---|---|---|
| **断言通过率** | **100%** | 82% | **+18 个百分点** |
| **墙钟时间（均值）** | **72 s** | 97 s | **快约 26%** |
| 输出 token（均值） | 54.4 k | 53.2 k | +2%（读取 SKILL.md 的一次性成本） |

| 任务 | 通过（技能） | 通过（基线） | 技能的差异所在 |
|---|---|---|---|
| 搜索 · 3 条 query 找同源 | 5/5 | 4/5 | 基线将 8 个 BLAST 库二进制文件遗留在交付目录；技能在临时目录建库 |
| 比较 · 4 基因组 ANI + 同种判定 | 4/4 | 4/4 | 正确性持平；技能快约 37%，矩阵洁净、无日志残留 |
| 系统发育 · 8 条 groEL ML 树 | 4/4 | 4/4 | 持平；两者均正确报告该树不可分辨（序列近乎同一），未过度宣称 |
| 出图 · 可发表级 ANI 热图 | 4/4 | **2/4** | 基线仅导出屏幕分辨率 PNG、无 600 dpi TIFF；技能恒定导出 SVG + PDF + TIFF（600 dpi，LZW） |

**解读。** 技能集在生物学正确性上与认真的基线持平，差异集中于可发表性与可复现性：（i）每次运行均记录 `工具 + 版本 + 命令` 溯源脚注，无引导的运行记录不一致；（ii）可发表级输出恒为可编辑 SVG + PDF + 600 dpi TIFF，遵循克制的 Nature 风格排版，基线仅产屏幕分辨率栅格图；（iii）交付目录仅保留结果，临时数据库限于临时目录；（iv）调用经加固的捆绑脚本而非重新推导命令行参数，使墙钟时间缩短约 26%。

### 二、持久化与记忆一致性基准（2.0 vs 无技能基线）

针对 2.0 的核心机制——由事件账本承担跨阶段状态权威——构建多阶段比较基因组学任务：逐基因组组装统计 → 全对全 ANI → 同种对判定 → 引用前序数值的书面小结 → 末端复述关键数值。两种配置仅在是否由 2.0 持久化内核驱动上存在差异；执行与评分均使用 claude-opus-4-8[1m]，评分代理独立复算全部数值。完整实验设计、逐项评分、运行遥测与原始证据见 [`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md)。

> **得分接近；决定性差异在机制不在分值——基线靠回忆复述，durable loop 从已密封提交读回。**

| 指标 | 无技能基线 | 2.0 durable loop | 说明 |
|---|---|---|---|
| memory_drift（记忆漂移） | 1.00 | 1.00 | 两次复述三值均与各自已算值完全吻合；机制不同（见下） |
| output_hygiene（产物规范性） | 0.95 | **1.00** | durable loop 临时存储即预期持久化位置 |
| 输出 token（评测记录） | 11,294 | **10,327（约 −8.6%）** | 当前配置下未观察到额外输出开销 |
| 输入 token（评测记录） | 31,632 | 31,660（约 +0.1%） | 基本一致 |
| academic_completeness（学术完整性） | 0.95 | 0.95 | 两者均可复现 |
| correctness（正确性） | **1.00** | 0.98 | 0.02 为报告完备性（未标注 fastANI minimizer 抖动），非科学错误 |
| stages_completed（完成阶段） | 4 | 3（已密封提交） | 计数口径不同，非能力差异（基线计 4 逻辑步；durable loop 计已封章阶段，02-compare-aai 因 EzAAI 缺失按设计暂停） |

**解读。** 两种配置在当前任务集上的评分接近，决定性差异在于状态恢复与数值复述的**实现机制**。基线直接从模型上下文复述关键数值；durable loop 则从已提交、已密封的阶段产物读取，并由 C-1 四证据闸门、SHA-256 对象摘要与哈希链事件序列共同约束。因而，后者将数值一致性建立在可查询的持久化事实之上，而非上下文记忆。当前配置下，durable loop 的输出 token 为 10.3k，低于基线的 11.3k，输入 token 基本一致；这一差异与 CLI 承担阶段编排、减少模型侧工具调用组装相一致。

*记忆一致性定义为末端复述值与相应计算结果的一致程度。两种配置均正确识别出一个同种组合（*S. vesiculosa* M7 与 PB002_L5，ANI ≈ 98.5%，对应同一物种的不同菌株）。评分 prompt 中“应无同种组合”的预设与 FASTA 标识及仓库既有分析不一致；该偏差及其复核证据已完整记录于 [`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md)。*

## 触发契约

六个技能分别提供 `evals/trigger_evals.json`，合计包含 **67 条** should-trigger / should-not-trigger 查询（12 + 11 + 11 + 12 + 11 + 10）。这些文件定义技能的触发契约，并作为描述变更后的回归检查集；其结构遵循 `skill-creator` 的 eval-set schema。另以 20 条边界路由查询检验技能间的判别性，覆盖既有结果的再处理、完整流程与单步请求、相邻技能歧义以及不应触发任何技能的负样本。当前版本经人工复核的路由一致率为 **20/20**。该指标仅评价触发规则与预期路由的一致性，不评价下游分析的科学正确性。

## 依赖

运行时依赖分为内核依赖与分析工具依赖。**2.0 持久化内核仅使用 Python 标准库，不需要额外的 pip 包**。外部生物信息学工具统一从 **`bio_tools` conda 环境**解析，并仅在相应分析阶段执行：

- 质控与注释：seqkit、Prokka；CheckM2、Flye、eggNOG-mapper、dbCAN 用于可选或计算密集阶段
- 比较：FastANI、EzAAI、OrthoFinder、MUMmer4
- 系统发育：MAFFT、trimAl、IQ-TREE、FastTree、PAML（codeml）、PAL2NAL
- 搜索：BLAST+、DIAMOND、HMMER
- 出图：Python（pandas / matplotlib）或 R（ggplot2 / svglite / ragg）

vivarium 不修改用户的分析环境，也不自动安装缺失的软件或数据库。依赖缺失时，系统返回明确诊断，并将相应阶段路由为外部执行或待补充状态，而不会产生未经验证的替代结果。

## 设计原则

- **持久化状态与可重放恢复。** 流程状态仅由追加事件账本定义；恢复过程重放已验证事件，并对已提交阶段保持幂等。当前跨运行确定性依赖系统发育阶段固定随机种子及 `--out` 工作区相对化；CRLF 归一、EzAAI 标签规范化、固定中间目录等跨环境一致性措施仍在完善，详见 [`docs/V1_V2_INTEGRATION.zh-CN.md`](docs/V1_V2_INTEGRATION.zh-CN.md)。
- **失败闭合的提交语义。** 阶段仅在 C-1 四证据对象全部复核通过后进入 COMMITTED；非零退出、空产物或证据绑定不一致均终止提交，不改变已确认状态。
- **显式执行边界。** 资源开销可控且依赖完备的阶段可就地执行；计算密集或需专用环境的阶段仅生成可审计命令与预期产物契约，由用户或集群执行后再回收验证。
- **环境非侵入性。** vivarium 不自动安装软件、数据库或修改用户环境；所有依赖变更均由用户显式授权。
- **结构化溯源。** 每个分析脚本记录工具名称、版本与精确命令，并采用统一完成记录 `=== vivarium-… done === / tool: <名称>(<版本>) / command: <精确命令>`。六个分析脚本及 matplotlib、ggplot2 两个出图后端均遵循该约定，为结果复核和方法学整理提供机器可读依据。
- **证据约束的科学表达。** 图表、摘要与结论必须可追溯至已验证产物；输出层负责组织和呈现证据，不改变分析结果，也不以图形质量替代科学有效性判断。
- **可恢复的文件生命周期。** 清理操作采用软删除，将目标移入 `_deleted/`，以保留误操作后的恢复路径。
- **模型无关的执行接口。** 参数组合、工具调用和产物契约封装于版本化脚本及内核接口中，模型主要负责选择受约束操作并解释结构化输出。该设计降低了对模型临时规划的依赖；不同模型后端之间的等价性仍需独立验证。

## 适用范围与实现边界

- **基准范围。** README 所列指标限定于仓库提供的任务、输入数据、工具版本与执行配置，用于验证当前实现的行为与交付规范，不构成对其他模型、硬件平台或工作流系统的普遍性能排序。
- **集群作业的自动提交与轮询尚未实现**——内核生成可提交的 sbatch/qsub 脚本，但提交与轮询留待后续版本。
- **若干确定性项仍在路线图上**（CRLF 归一、EzAAI 标签规范化、固定中间目录、TIFF 栅格化跨环境确定性），详见 [`docs/V1_V2_INTEGRATION.zh-CN.md`](docs/V1_V2_INTEGRATION.zh-CN.md)。
- **「可发表级」指输出格式与可复现性**（可编辑 SVG + PDF + 600 dpi TIFF、克制排版、版本化溯源），不代表科学结论已达可发表水平。

## 许可

见 `LICENSE`（MIT）。
