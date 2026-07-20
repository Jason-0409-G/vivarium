# Changelog

本插件遵循[语义化版本](https://semver.org/lang/zh-CN/)（`MAJOR.MINOR.PATCH`），版本号写在 `.claude-plugin/plugin.json` 的 `version`。**用户只在版本号 bump 时收到更新**；更新方式见 [README「更新」一节](README.md#更新)。

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
