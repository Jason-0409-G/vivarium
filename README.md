# vivarium

<p align="center">
  <a href="docs/media/vivarium-v2-durable-loop-4k.png">
    <img src="docs/media/vivarium-v2-durable-loop-4k.png" alt="Vivarium 2.0 事件溯源、崩溃安全与证据闸门机制图" width="100%">
  </a>
</p>
<p align="center"><sub>Vivarium 2.0 durable loop：PLAN → ROUTE → EXECUTE → VALIDATE → C-1 COMMIT GATE → SEAL；点击查看 4K 原图。</sub></p>

> [English](README.en.md) ｜ **中文**
>
> 面向本地比较基因组学的持久化分析执行系统，以 Claude Code 技能集形式交付。

## 概述

**vivarium** 是一套在本地开展比较基因组学分析的 Claude Code 技能集。给定一组基因组组装与一个分析目标，系统将分析规划为阶段图（DAG），在 `bio_tools` conda 环境中执行各阶段，并产出可发表级的图表与可直接写入方法学的溯源记录。系统采用**混合执行**模型：轻量分析（组装质控、ANI/AAI、比对建树、序列搜索、绘图）就地执行；计算密集或耗时的阶段（从头组装、eggNOG/dbCAN 功能注释、OrthoFinder 直系同源推断、大规模系统发育、PAML 选择压检验）以可执行命令的形式生成，交由用户在本机或计算集群运行，其产物经回收后由系统解读。

自 2.0 起，系统的执行层由一套**持久化、崩溃安全、事件溯源**的内核承担（详见下节）：1.0 以一份可变 JSON 清单（`run_manifest.json`）记录流程状态，进程中断、写入截断或跨阶段状态失真均可能导致该清单静默损坏；2.0 将其替换为仅追加（append-only）的事件账本，每一阶段的真实产物经密封后写入账本，账本构成流程状态的唯一权威来源。1.0 的全部分析脚本保持独立可用，2.0 通过一层通用适配器将其作为持久化阶段驱动，默认行为不变。

vivarium 与论文写作技能集 [`scriptorium`](https://github.com/Jason-0409-G/scriptorium)（research-to-paper）互为配套：scriptorium 将研究整理为论文，vivarium 将基因组转化为结果。

## 2.0 持久化执行内核

2.0 将比较基因组学流程建模为一台**事件溯源的状态机**，其设计目标为确定性恢复、提交前校验与资源感知调度。

**事件溯源账本。** 每一阶段的执行产物经受限 RFC-8785/JCS 规范化 JSON 编码、域分隔 SHA-256 摘要后，追加写入仅追加的 JSONL 账本；写入遵循文件先于目录的 fsync 定序，并对撕裂尾部（torn tail）进行隔离。进程在任意点中断后，系统可自账本按字节确定性重建流程状态，且对已提交阶段幂等，不重复执行。

**C-1 提交闸门。** 一个阶段进入 COMMITTED 之前，必须对四个持久化证据对象——证据包（evidence bundle）、成功完成记录、法定通过裁决（quorum pass）、完成证明（completion proof）——重新校验，且四者均须绑定到已提交的 run/cut/claim/contract。空产物或非零退出码在提交前被拦截，不进入账本，从而杜绝失败阶段污染下游状态。

**资源感知路由。** `probe_device()` 探测本机核数、物理内存与集群调度器（sbatch/qsub/bsub）的存在性；`route_stage()` 据此为每一阶段判定执行位置：
- `local_inline`——所需工具已安装且资源可容纳，就地执行并提交；
- `cluster`——阶段计算量超出本机容量但存在调度器，生成可直接提交的 sbatch/qsub 作业脚本；
- `scaffold_local`——工具缺失或资源不足且无调度器，生成命令交由用户外部执行，产物经回收后校验入账。

该路由为资源感知的启发式判定（对超出容量的阶段保守拦截），并非精确耗时预测；作业脚本生成已实现，集群作业的自动提交与轮询留待后续版本。

**可驱动、可恢复的 DAG。** `vivarium v2 plan/run` 将四个目标（`compare-genomes` / `phylogeny` / `selection` / `full`）展开为有序阶段图，每一阶段携带确切命令、期望产物、依赖边与路由决策。驱动过程自动执行就地阶段，在首个需人工介入或需集群提交的阶段暂停并预建工作目录；用户回收产物后再次驱动，流程自持久账本恢复并续跑。

```bash
# 打印设备探测结果、逐阶段路由决策、确切命令与期望产物
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    plan --root ./store --goal compare-genomes --genomes ./genomes

# 驱动流程：就地阶段自动执行并提交，scaffold/cluster 阶段暂停待人工
PYTHONPATH=. python3 -m skills.vivarium.vivarium_v2.cli \
    run  --root ./store --goal compare-genomes --genomes ./genomes
```

内核与 1.0 脚本的融合细节见 [`docs/V1_V2_INTEGRATION.zh-CN.md`](docs/V1_V2_INTEGRATION.zh-CN.md)。

## 技能

| 技能 | 功能 | 就地执行 / 生成命令 |
|---|---|---|
| **`vivarium`** | 伞型协调器：目标 → 分析 DAG → 串联各子技能 → 持久化账本追踪 → 重活阶段暂停/续跑 | 协调 |
| **`vivarium-prep`** | 组装质控（contigs / N50 / GC / 完整度）；注释（Prokka → eggNOG / dbCAN） | `stats` 就地执行；组装 / eggNOG / dbCAN 生成命令 |
| **`vivarium-compare`** | 基因组亲缘度（FastANI / EzAAI 的 ANI/AAI）；直系同源（OrthoFinder）；共线性（MUMmer） | ANI / AAI / synteny 就地执行；OrthoFinder 生成命令 |
| **`vivarium-phylo`** | 比对 → 修剪 → 建树（MAFFT / trimAl / IQ-TREE）；选择压（PAML dN/dS） | `tree` 就地执行；PAML 生成命令 |
| **`vivarium-search`** | 序列相似性搜索（BLAST / DIAMOND / HMMER） | 就地执行 |
| **`vivarium-report`** | 可发表级图表（Python matplotlib / R ggplot2）；导出 SVG + PDF + TIFF（600 dpi） | 就地执行 |

各技能均可独立触发，亦可由伞型 `vivarium` 或 2.0 内核串联为端到端流程。

## 基准评测

### 一、技能有效性基准（带技能 vs 无技能基线）

在四个代表性任务（搜索 / 比较 / 系统发育 / 出图）上评测，使用同一套 prompt 与同一 `bio_tools` 环境，以「是否提供该技能」为唯一自变量。任务由 claude-opus-4-8（general-purpose 子代理）执行，每种配置各一次（单机单跑，属方向性证据而非统计功效结论）。完整数据与逐条断言证据见 [`benchmark/benchmark.md`](benchmark/benchmark.md)。

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

针对 2.0 的核心命题——事件溯源账本作为唯一权威来源可消除跨阶段的记忆漂移——设计一项多阶段比较基因组学任务（逐基因组组装统计 → 全对全 ANI → 同种对判定 → 引用前序数值的书面小结 → 末端复述关键数值）。以「是否经 2.0 持久化内核驱动」为自变量，测量 token 消耗、产物数量与规范性、记忆一致性（末端复述值与自身已算数值的吻合度）及学术完整性（溯源与可复现性）。方法学与 1.0 基准一致（单机单跑，方向性证据）。完整设计、逐项评分与遥测数据见 [`benchmark/benchmark_v2.md`](benchmark/benchmark_v2.md)。

| 指标 | 无技能基线 | 2.0 durable loop |
|---|---|---|
| correctness（正确性） | **1.00** | 0.98 |
| memory_drift（记忆漂移） | 1.00 | 1.00 |
| academic_completeness（学术完整性） | 0.95 | 0.95 |
| output_hygiene（产物规范性） | 0.95 | **1.00** |
| stages_completed（完成阶段） | 4 | 3（已密封提交） |
| 输出 token（单跑实测） | 11,294 | **10,327（约 −8.6%）** |
| 输入 token（单跑实测） | 31,632 | 31,660（约 +0.1%） |

**解读。** 二者本次得分接近，核心差异不在分值而在**机制**：基线末端**凭个人回忆**复述三个关键数值（本单跑恰好全部命中），其正确性由回忆本身承担、随上下文与阶段数增长而承压；durable loop 的复述则**从已提交/已密封的阶段产物读回（账本即记忆）**，经 C-1 四证据闸门校验、以 sha256 object head 与哈希链事件流固定，其正确性与上下文长度无关。两配置均生物学正确地判出恰好 1 个同种对（*S. vesiculosa*_M7 + PB002_L5，ANI ≈ 98.5%——二者实为同一物种的两个菌株）。**token 消耗按代理实测：驱动持久化内核并未引入开销**——durable loop 输出 token 反而略低（10.3k vs 11.3k），输入 token 几近持平，因 CLI 承担阶段编排、模型无需逐条自拼工具调用，抵消了读回产物与维护账本的成本（单跑，不外推）。

**相对 1.0 的提升。** 1.0 无持久化、无账本、以可变 JSON 清单（`run_manifest.json`）记状态，且**从不测量记忆漂移**；2.0 以仅追加事件账本替换该清单——崩溃后可按字节确定性重建、对已提交阶段幂等，账本构成流程状态的唯一权威来源，从而把「复述」转化为对不可变已提交事实的读回。这正是 2.0 能将记忆漂移作为一等指标测量的前提。

*单跑、方向性证据，非有功效的统计断言；记忆漂移以「复述值 vs. 自身已算值」的一致性度量。*

## 触发命中率

在一组刻意设置边界难度的 20 条路由查询上——包括「渲染一棵已有的树」（应走 report 而非 phylo）、「ANI 已算好、绘制成图」（应走 report 而非 compare）、整流程与单步请求，以及四条不应触发任何技能的负样本（撰写方法、润色摘要、天气、总结 PDF）——六个技能描述全部路由正确（**20/20 = 100%**）。每个技能另附 `evals/trigger_evals.json`（共 67 条 should-/should-not-trigger 查询），既作为触发契约，又作为回归护栏；配置 API key 后，可经 `run_loop.py --eval-set <file>` 直接馈入官方 `skill-creator` 优化器。

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

## 更新

本插件采用**语义化版本号**（`.claude-plugin/plugin.json` 的 `version` 字段）。仅当版本号递增时，用户方收到更新；每版变更见根目录 [`CHANGELOG.md`](CHANGELOG.md)。

**插件市场安装**
```
/plugin marketplace update vivarium     # 拉取最新目录
/plugin update vivarium@vivarium        # 安装新版本
/reload-plugins                         # 本会话即时生效（或重启）
```
亦可在 `/plugin` → Marketplaces 中为 `vivarium` 启用 **auto-update** 自动更新。

**脚本安装**
```bash
cd vivarium   # 先前克隆的目录
git pull
bash install.sh
```

## 依赖

分析工具须位于 **`bio_tools` conda 环境**（技能从不自动安装，缺失仅提示）：
- 质控 / 注释：seqkit、Prokka、（CheckM2、Flye、eggNOG-mapper、dbCAN——可选 / 重活）
- 比较：FastANI、EzAAI、OrthoFinder、MUMmer4
- 系统发育：MAFFT、trimAl、IQ-TREE、FastTree、PAML（codeml）、PAL2NAL
- 搜索：BLAST+、DIAMOND、HMMER
- 出图：Python（pandas / matplotlib）或 R（ggplot2 / svglite / ragg）

2.0 内核为纯标准库实现，无额外运行时依赖；上述工具仅在对应分析阶段就地执行时需要。

## 设计原则

- **持久化与确定性恢复。** 状态记录于仅追加的事件账本，进程中断后可按字节确定性重建，对已提交阶段幂等。
- **提交前校验。** 阶段提交须通过 C-1 四证据闸门，失败或空产物不入账。
- **混合执行。** 轻量步骤就地执行，重活以命令形式生成交由用户运行，不无人值守地执行长任务。
- **绝不自动安装。** 缺失的工具或数据库仅提示，由用户决定。
- **溯源（每步记录软件版本号）。** 每个脚本运行后打印统一脚注 `=== vivarium-… done === / tool: <名>(<版本>) / command: <精确命令>`；六个分析脚本与两个出图后端（matplotlib / ggplot2，含各自版本）已统一，输出可直接写入方法学。
- **图服务于科学逻辑。** 不过度宣称，n = 1 不外推。
- **软删除。** 不使用 `rm`，需清理的文件移入 `_deleted/`。
- **对较弱的非 Claude 模型稳健。** 每一步均为「运行确定命令并读取其输出」；分析逻辑全部位于捆绑脚本中（FastANI / IQ-TREE / BLAST 等及统一溯源脚注），模型既不自行拼装参数，也不编排多步工具调用，因而在非 Claude 后端（如 `deepseek-v4-pro[1m]`，子代理使用 `deepseek-v4-flash`）上同样稳定。

## 许可

见 `LICENSE`（MIT）。
