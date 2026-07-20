<p align="center">
  <a href="docs/media/vivarium-v2-durable-loop-4k.png">
    <img src="docs/media/vivarium-v2-durable-loop-4k.png" alt="Vivarium 2.0 事件溯源、崩溃安全与证据闸门机制图" width="100%">
  </a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f.svg?style=flat-square" alt="MIT license"></a>
  <a href="https://github.com/Jason-0409-G/vivarium/releases"><img src="https://img.shields.io/badge/release-v2.0.1-0969da.svg?style=flat-square" alt="release v2.0.1"></a>
  <img src="https://img.shields.io/badge/clients-Claude_Code_%7C_Codex-24292f.svg?style=flat-square" alt="Claude Code and Codex">
  <img src="https://img.shields.io/badge/skills-6-0ea5e9.svg?style=flat-square" alt="6 skills">
  <img src="https://img.shields.io/badge/status-actively_maintained-2ea44f.svg?style=flat-square" alt="actively maintained">
  <a href="README.en.md"><img src="https://img.shields.io/badge/language-English-2563eb.svg?style=flat-square" alt="English README"></a>
</p>

<p align="center">
  <a href="#项目状态">项目状态</a> ·
  <a href="#安装">安装</a> ·
  <a href="#触发完整流程">快速开始</a> ·
  <a href="#核心机制与技术定位">核心机制</a> ·
  <a href="#技能索引">技能索引</a> ·
  <a href="#基准评测">基准评测</a> ·
  <a href="README.en.md">English</a>
</p>

---

**vivarium 是面向比较基因组学的双端工作流 skill 集与持久化执行内核。** 它将分析目标展开为可验证、可恢复且可审计的阶段图，并在 Claude Code 与 Codex 中提供一致的工作流契约。

## 项目状态

| 项目 | 当前状态 |
|---|---|
| **维护状态** | **持续维护与迭代**；后续版本依据真实数据基准、跨端兼容性验证和用户反馈增量发布 |
| **当前版本** | `v2.0.1`；2.0 为当前主线，1.0 分析脚本继续保持独立可用 |
| **支持端** | Claude Code 插件与 Codex skills；两端共享同一组 `SKILL.md` 工作流契约 |
| **版本记录** | 语义化版本号、[`CHANGELOG.md`](CHANGELOG.md) 与 [GitHub Releases](https://github.com/Jason-0409-G/vivarium/releases) |
| **开发路线** | 14 个公开任务的输入、实现、产物、验收、依赖、风险与状态见 [`docs/VIVARIUM_V2_TASKS.zh-CN.md`](docs/VIVARIUM_V2_TASKS.zh-CN.md) |

> 尚未完成的能力会在路线图和发布说明中明确标记。集群作业自动提交与轮询仍属于后续版本范围。

## 安装

Claude Code 与 Codex 是两个平级支持端。二者提供相同的六项工作流能力，仅分发与更新机制不同。

| | **Claude Code** | **Codex** |
|---|---|---|
| **推荐入口** | 插件市场 | `$skill-installer` |
| **分发单元** | 一个插件，包含伞型技能与五个子技能 | 六个独立 skill 路径 |
| **默认位置** | Claude Code 插件缓存 | `$CODEX_HOME/skills`，默认 `~/.codex/skills` |

### Claude Code

在 Claude Code 中依次执行：

```text
/plugin marketplace add Jason-0409-G/vivarium
/plugin install vivarium@vivarium
/reload-plugins
```

仓库当前默认分支为 `master`。如需显式锁定分支，可将第一条命令改为：

```text
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git#master
```

### Codex

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

必须保留 `--ref master`，因为 `$skill-installer` 默认尝试 `main`。若新技能未立即出现在列表中，请重启 Codex。

<details>
<summary><strong>本地脚本安装（Claude Code、Codex 或同时安装）</strong></summary>

```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh --target claude   # 安装到 ~/.claude/skills/
bash install.sh --target codex    # 安装到 $CODEX_HOME/skills
bash install.sh --target both     # 同时安装到两端
```

安装脚本不会直接删除已有同名技能。旧目录会先重命名为带时间戳的备份，再写入新副本。

</details>

<details>
<summary><strong>Codex 用户级符号链接安装</strong></summary>

```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
mkdir -p "$HOME/.agents/skills"
for skill in vivarium vivarium-prep vivarium-compare vivarium-phylo vivarium-search vivarium-report; do
    ln -s "$PWD/skills/$skill" "$HOME/.agents/skills/$skill"
done
```

该方式保留单一源码副本，后续执行 `git pull` 即可更新链接目标。仅在当前仓库启用时，可将链接建立在项目根目录的 `.agents/skills` 中。

</details>

## 更新

正式版本由 `.claude-plugin/plugin.json` 的 `version` 字段标识。只向 `master` 推送代码而不递增版本号，不会触发插件版本更新。

| 安装方式 | 更新方法 |
|---|---|
| **Claude Code 插件市场** | `/plugin marketplace update vivarium` → `/plugin update vivarium@vivarium` → `/reload-plugins` |
| **Codex `$skill-installer`** | 按安装章节重新同步六个路径，并继续指定 `--ref master` |
| **本地脚本副本** | `git pull` 后重新执行 `bash install.sh --target claude`、`codex` 或 `both` |
| **Codex 符号链接** | 在链接指向的仓库中执行 `git pull` |

Claude Code 可在 `/plugin` → Marketplaces 中为 `vivarium` 启用自动更新。当前会话仍显示旧版本时，请重新加载插件或重启相应客户端。

## 触发完整流程

“完整流程”由伞型 `vivarium` 技能驱动 2.0 持久化内核的 `full` 目标。建议显式调用，以避免自然语言请求被路由到单步子技能。

| **Claude Code** | **Codex** |
|---|---|
| `/vivarium:vivarium` | `$vivarium` |

**Claude Code**

```text
/vivarium:vivarium 请对 ./genomes 运行 vivarium 2.0 完整持久化流程。使用 full 目标，先输出 DAG 与本地/集群路由，再执行可就地阶段；将状态写入 ./vivarium_store。遇到 cluster 或 scaffold 阶段时暂停，并返回确切命令、预期产物与回收位置。
```

**Codex**

```text
Use $vivarium to run the full vivarium 2.0 durable workflow over ./genomes. Use the full goal, print the DAG and local/cluster routing before execution, persist state under ./vivarium_store, run eligible local stages, and pause at cluster or scaffold stages with the exact command, expected artifacts, and collection path.
```

也可从仓库根目录直接驱动同一内核：

```bash
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    plan --root ./vivarium_store --goal full --genomes ./genomes

PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    run --root ./vivarium_store --goal full --genomes ./genomes
```

`full` 当前展开为：组装统计 → 注释 → ANI → AAI → 直系同源 → 共线性 → 系统发育树 → 热图。序列搜索与 PAML 选择分析需要额外输入，不会在缺少查询序列、数据库或密码子比对时被自动加入。

## 核心机制与技术定位

LLM 驱动的长流程存在两类状态风险：可变清单可能在中断或部分写入后失真，模型上下文也可能在跨阶段复述时偏离真实产物。vivarium 2.0 将流程状态从模型记忆和可变文件迁移到仅追加、哈希链的事件账本，并在提交前执行失败闭合的证据校验。

### Durable loop

| 阶段 | 作用 | 可验证结果 |
|---|---|---|
| **PLAN** | 将目标展开为有序 DAG | 确切命令、期望产物与依赖边 |
| **ROUTE** | 探测 CPU、内存、工具与调度器 | `local_inline`、`cluster` 或 `scaffold_local` |
| **EXECUTE** | 在隔离进程中运行真实工具 | 退出码、标准输出、标准错误与产物 |
| **VALIDATE** | 检查退出状态与非空产物 | 失败阶段不得进入提交路径 |
| **C-1 GATE** | 复核四个持久化证据对象 | 证据包、成功完成记录、quorum pass、完成证明 |
| **SEAL** | 规范化、摘要、同步并追加事件 | 不可变、可查询的已提交事实 |
| **RECOVER** | 重放已验证事件 | 对已提交阶段幂等，不重复执行 |

事件对象采用受限 RFC 8785/JCS 规范化 JSON、域分隔 SHA-256 摘要和仅追加 JSONL 账本。写入执行 fsync 定序，并隔离未完成的尾行。这里的“确定性恢复”特指**由同一账本按字节重建流程状态**，不表示不同操作系统、工具版本或硬件上的生物信息学计算必然产生位级一致结果。

C-1 闸门要求四个证据对象均绑定到已提交的 run/cut/claim/contract。非零退出码、空产物或证据绑定不一致会在密封前终止提交，避免失败状态进入下游。

### 1.0 与 2.0 的关系

2.0 不是对分析脚本的整体重写，而是在 1.0 分析能力之上增加持久化控制与执行层。1.0 脚本仍可独立调用；2.0 通过 `v1_adapter.py` 将其纳入可恢复阶段图。

| 维度 | 1.0 | 2.0 |
|---|---|---|
| 状态权威 | 可变 `run_manifest.json` | 仅追加、哈希链事件账本 |
| 崩溃恢复 | 中断后需人工判断状态 | 自账本重放，对已提交阶段幂等 |
| 提交校验 | 无统一提交闸门 | C-1 四证据闸门 |
| 编排 | 脚本串联 | 可驱动、可恢复的 DAG |
| 资源路由 | 无 | 本地、集群脚本或外部 scaffold |

完整迁移设计见 [`docs/V1_V2_INTEGRATION.zh-CN.md`](docs/V1_V2_INTEGRATION.zh-CN.md)。

### 与其他工作流系统的边界

Snakemake 与 Nextflow 提供更成熟的静态 DAG、调度器集成和集群作业生命周期管理。vivarium 的重点是 LLM 原生的目标解析、skill 契约、提交前证据校验和事件溯源状态。二者并非互斥：vivarium 可生成可审计的外部命令或作业脚本，但当前不会自动提交或轮询集群任务。

只需执行一次 ANI、BLAST 或绘图时，应直接调用相应子技能。需要成熟的无人值守集群调度，或完全不涉及 LLM 编排的静态流程时，应优先采用 Snakemake 或 Nextflow。

## 技能索引

| 技能 | 核心职责 | 执行边界 |
|---|---|---|
| **`vivarium`** | 目标解析、阶段图构建与子技能编排 | 完整流程默认由 2.0 事件账本承担状态权威 |
| **`vivarium-prep`** | 组装统计、质量评估与注释 | 轻量阶段就地执行；重计算阶段生成外部命令 |
| **`vivarium-compare`** | ANI/AAI、直系同源与共线性 | FastANI、EzAAI、MUMmer 按依赖执行；OrthoFinder 默认外部运行 |
| **`vivarium-phylo`** | 比对、修剪、建树与密码子选择分析 | 常规建树可就地执行；大规模分析与 PAML 可转为外部阶段 |
| **`vivarium-search`** | BLAST、DIAMOND 与 HMMER 检索 | 工具和数据库可用时就地执行，缺失时返回明确诊断 |
| **`vivarium-report`** | 标准化图表、表格与方法学记录 | 导出可编辑 SVG、PDF 与 600 dpi TIFF |

六项技能均可独立触发，也可由伞型技能组合为端到端阶段图。

## 基准评测

### Skill 有效性

四类任务在相同提示、输入与 `bio_tools` 环境下比较有 skill 与无 skill 基线。完整输入、原始输出和逐断言证据见 [`benchmark/benchmark.md`](benchmark/benchmark.md)。

| 指标 | 有 skill | 无 skill 基线 | 差异 |
|---|---:|---:|---:|
| 断言通过率 | **100%** | 82% | **+18 个百分点** |
| 平均墙钟时间 | **72 s** | 97 s | **约快 26%** |
| 平均输出 token | 54.4 k | 53.2 k | +2% |

正确性差异主要来自交付规范与可复现性。skill 组统一记录工具、版本和精确命令，并稳定导出 SVG、PDF 与 600 dpi TIFF；无 skill 基线在出图任务中仅满足 2/4 项交付断言。

### 持久化与记忆一致性

第二组基准使用四个真实 *Shewanella* 基因组，对比 2.0 durable loop 与无 skill 基线。完整设计、运行遥测和独立复算证据见 [`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md)。

| 指标 | 无 skill 基线 | 2.0 durable loop |
|---|---:|---:|
| `memory_drift` | 1.00 | 1.00 |
| `output_hygiene` | 0.95 | **1.00** |
| 输出 token | 11,294 | **10,327** |
| 输入 token | 31,632 | 31,660 |
| `academic_completeness` | 0.95 | 0.95 |
| `correctness` | **1.00** | 0.98 |

两组在本次任务中均准确复述关键数值。差异在机制而非该次分数：基线依赖模型上下文，durable loop 从已密封产物读回。`correctness` 的 0.02 差异来自 fastANI minimizer jitter 未在报告中说明，属于报告完整性问题而非生物学判定错误。

本次数据识别出一个同种配对：*S. vesiculosa* M7 与 PB002_L5，ANI 约 98.5%。评分提示中“无同种配对”的预期与 FASTA 标识及仓库既有分析不一致，证据见基准文档。

> 上述指标仅适用于仓库记录的任务、数据、工具版本、模型与执行环境，不构成跨模型、跨硬件或跨工作流系统的普遍性能排名。

## 触发契约

六项技能共包含 **69** 条 should-trigger 与 should-not-trigger 查询。另有 20 条相邻技能边界查询，当前人工复核为 **20/20** 路由一致。该结果仅验证触发规则的一致性，不评价后续生物信息学分析的科学正确性。

## 依赖与实现边界

2.0 持久化内核仅使用 Python 标准库，不需要额外 pip 运行时依赖。分析工具从 `bio_tools` conda 环境解析，并仅在对应阶段调用。

- **质控与注释：** seqkit、Prokka；CheckM2、Flye、eggNOG-mapper、dbCAN 用于可选或重计算阶段。
- **比较：** FastANI、EzAAI、OrthoFinder、MUMmer4。
- **系统发育：** MAFFT、trimAl、IQ-TREE、FastTree、PAML、PAL2NAL。
- **检索：** BLAST+、DIAMOND、HMMER。
- **出图：** Python（pandas、matplotlib）或 R（ggplot2、svglite、ragg）。

vivarium 不自动安装软件或数据库，不修改用户分析环境。缺失依赖会产生明确诊断，并将阶段转为外部执行或待处理状态。

当前实现边界：

- 集群作业脚本生成已实现，自动提交与轮询尚未实现。
- 资源路由是保守的启发式判定，不是精确运行时间预测。
- 跨环境位级确定性仍受工具版本、随机种子、换行规范化和图形后端影响。
- “可发表级”仅指输出格式、排版约束与溯源完整性，不代表科学结论已经达到发表标准。
- 清理操作采用软删除，将目标移入 `_deleted/` 以保留恢复路径。

## 许可

见 [`LICENSE`](LICENSE)（MIT）。
