# Changelog

本插件遵循[语义化版本](https://semver.org/lang/zh-CN/)（`MAJOR.MINOR.PATCH`），版本号写在 `.claude-plugin/plugin.json` 的 `version`。**用户只在版本号 bump 时收到更新**；更新方式见 [README「更新」一节](README.md#更新)。

## [2.0.2] - 2026-07-20

围绕 durable loop 的一轮代码级对抗测试发现并修复了两处真缺陷，并据多模型基准补充了"按规模决策"的使用判据。全套 205 测试通过。

### 修复
- **P1 崩溃恢复"既提交又中止"**：当 `ledgers/work.jsonl` 被撕裂的最后一行恰是一条已提交的 `STAGE_COMMITTED` 记录时，`recover()` 会既隔离它、又（非原子地）把同一事务判为 `STAGE_COMMIT_ABORTED`，修复该字节后同一 `commit_tx_id` 同时存在两种结果。现改为在 COMMIT_INTENT 恢复循环**之前**对 work 账本撕裂尾 fail-closed（与 `capture()` 一致），绝不先写 abort。经对抗验证：bug 消除、幂等、5 个 COMMIT_CRASH_POINT 零回归。
- **P3 跨运行确定性**：OS `pid` 经四条通道（`process_start_identity`、`process_receipt_digest`、`process_or_job_ref`、以及扫入证据包的 `process-receipt.json` 构件）污染密封执行摘要，使确定性阶段两次独立运行的已提交事件不一致。现全部去 `pid`（`pid`/`process_group_id` 仍留在 receipt 供 `os.killpg` 回收）；确定性阶段重跑时，执行证据 cut 摘要、完成证明摘要、已提交 `evidence_bundle_digest` 与 `object_head` 均逐字节复现。

### 新增
- **按规模决策的使用判据**：`SKILL.md` 新增「Route by scale」——装得进上下文的单步/一次性分析直连子技能（最省、无正确性损失），仅在长流程/状态超出上下文/崩溃敏感/需可审计提交链/上集群时驱动内核。README（中英）新增「何时用内核」段，附规模交叉点图与硬证据。
- **权威测试报告**：`benchmark/AUTHORITATIVE_VERDICT.zh-CN.md` 与两张可复现数据图（`docs/figures/benchmark_scale_crossover.*`、`benchmark_2x3_tokens.*`）——能力排名、经对抗验证的硬保证、以及诚实反价值（小任务上内核为净成本）。

## [2.0.1] - 2026-07-20

### 变更
- 伞型 `vivarium` 技能将新的端到端请求默认路由到 V2 持久化内核；仅在用户明确要求 V1/legacy 时使用可变 manifest 编排器。
- 新增 Claude Code `/vivarium:vivarium` 与 Codex `$vivarium` 的完整模式触发示例，并提供 `--goal full` 的直接 CLI 入口。
- 为 V2 durable / event-ledger / C-1 完整模式补充伞型技能触发回归样本。
- 明确 `full` 是默认的完整基因组集合流程，不会在缺少查询序列、数据库、orthogroup 或密码子比对时擅自加入搜索与选择分析。
- 新增 Codex 技能界面元数据，默认提示指向 `full` durable workflow。
- `install.sh` 新增 `--target claude|codex|both`，为 Claude Code 与 Codex 提供平级的本地安装入口，并在覆盖前保留时间戳备份。

## [2.0.0] - 2026-07-20

**持久化执行内核。** 1.0 以可变 JSON 清单（`run_manifest.json`）记录流程状态；2.0 将执行层替换为一套持久化、崩溃安全、事件溯源的内核，把比较基因组学流程建模为可确定性恢复的阶段图。1.0 全部分析脚本保持独立可用，2.0 通过通用适配器将其作为持久化阶段驱动，默认行为不变。

### 新增
- **事件溯源账本**：受限 RFC-8785/JCS 规范化 JSON + 域分隔 SHA-256 + 撕裂尾隔离 + 文件先于目录的 fsync 定序；中断后按字节确定性恢复，对已提交阶段幂等。
- **C-1 提交闸门**：阶段提交前重新校验四个持久化证据对象（证据包 / 成功完成 / 法定通过 / 完成证明），并绑定到已提交的 run/cut/claim/contract；空产物与非零退出码在提交前被拦截，不入账。
- **资源感知路由**：`probe_device()` 探测核数 / 内存 / 集群调度器；`route_stage()` 判定 `local_inline` / `cluster`（生成可提交的 sbatch/qsub 脚本）/ `scaffold_local`。
- **可驱动、可恢复的 DAG**：`vivarium v2 plan/run` 将四个目标（compare-genomes / phylogeny / selection / full）展开为有序阶段图，自动执行就地阶段，在需人工或需集群处暂停并预建工作目录，回收产物后自持久账本续跑。
- **持久化与记忆一致性基准**（`benchmark/benchmark_v2.md`）：以事件溯源账本消除跨阶段记忆漂移为核心命题，测量 token 消耗、产物规范性、记忆一致性与学术完整性。

### 融合修复（V1 脚本配合 V2 内核，均非破坏性）
- 解释器 / 环境注入：适配层将 conda 前缀前置 PATH 并选定解释器，harness 透传，一处修复全部 5 个脚本。
- `--out` 须为 workspace 相对路径，防止 evidence 写至密封目录外而静默丢失。
- phylo 建树固定随机 seed（默认 42），保证跨运行 byte-identical，满足确定性恢复。

### 说明
- 内核为纯标准库实现，无额外运行时依赖；分析工具仅在对应阶段就地执行时需要。
- 融合细节见 `docs/V1_V2_INTEGRATION.zh-CN.md`。

## [1.0.0] - 2026-06-25

首个带版本号的正式发布。**vivarium**：本地比较基因组学分析工作流——一个伞型编排器 + 5 个可独立调用的模块。

### 模块
- **prep**：QC + 组装 + 注释。
- **compare**：直系同源 + ANI/AAI + 共线性。
- **phylo**：比对 + 建树 + 选择压（dN/dS）。
- **search**：序列检索（BLAST / DIAMOND / HMMER）。
- **report**：出图。

### 设计
- 混合执行：轻量分析在 `bio_tools` conda 环境直接跑；重活 / 长任务生成可直接运行的命令，交更大机器执行。
- **绝不自动安装**：缺失的工具 / 数据库只提示、不安装。
- 结果带版本溯源脚注；各 skill 自带触发评测集（`evals/trigger_evals.json`）；附带基准（带技能 vs 无技能基线）；DeepSeek 后端说明。
