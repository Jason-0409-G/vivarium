# Changelog

本插件遵循[语义化版本](https://semver.org/lang/zh-CN/)（`MAJOR.MINOR.PATCH`），版本号写在 `.claude-plugin/plugin.json` 的 `version`。**用户只在版本号 bump 时收到更新**；更新方式见 [README「更新」一节](README.md#更新)。

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
