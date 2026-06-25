# vivarium

本地比较基因组学分析工作流的 Claude Code 技能集。给 vivarium 一组基因组和一个目标，它规划并跑通比较基因组流程，产出可发表的图/表 + 方法学就绪的记录。**混合执行**：轻量分析在本地 `bio_tools` conda 环境直接跑，重/长任务（组装、eggNOG/dbCAN、OrthoFinder、大树、PAML）生成可直接执行的命令交你跑、结果回来再解读。

与写作技能集 [`scriptorium`](https://github.com/Jason-0409-G/scriptorium)（research-to-paper）成对：scriptorium 把研究写成论文，vivarium 把基因组跑成结果。

## 技能

| 技能 | 干什么 | 本地跑 / scaffold |
|---|---|---|
| **`vivarium`** | 伞型协调器：目标 → 分析 DAG → 串各子技能 → run_manifest 追踪 → 重活暂停/续跑 | 协调 |
| **`vivarium-prep`** | 基因组 QC（contigs/N50/GC/完整度）、注释（Prokka → eggNOG/dbCAN） | stats 跑；组装/eggNOG/dbCAN scaffold |
| **`vivarium-compare`** | ANI/AAI（FastANI/EzAAI）、直系同源（OrthoFinder）、共线性（MUMmer） | ANI/AAI/synteny 跑；OrthoFinder scaffold |
| **`vivarium-phylo`** | 比对 → 修剪 → 建树（MAFFT/trimAl/IQ-TREE）、选择压（PAML dN/dS） | tree 跑；PAML scaffold |
| **`vivarium-search`** | 序列搜索（BLAST/DIAMOND/HMMER） | 直接跑 |
| **`vivarium-report`** | 出版级图 + 表（Python matplotlib / R ggplot2），导出 SVG+PDF+TIFF 600dpi | 直接跑 |

每个技能都能单独触发，也能被伞型 `vivarium` 串成端到端流程。

## 性能基准（带技能 vs 无技能基线，实测）

4 个代表性任务（搜索 / 比较 / 建树 / 出图），**同一套 prompt、同一个 `bio_tools` 环境，唯一变量是「有没有这个技能」**。执行模型 claude-opus-4-8（general-purpose 子代理），每组合各 1 次（单机单跑，方向性证据，非统计功效结论）。完整数据 + 逐断言证据见 [`benchmark/benchmark.md`](benchmark/benchmark.md)。

| 指标 | 带技能 | 无技能基线 | 差值 |
|---|---|---|---|
| **断言通过率** | **100%** | 82% | **+18 pt** |
| **墙钟时间（均值）** | **72s** | 97s | **快 ~26%** |
| 输出 token（均值） | 54.4k | 53.2k | +2%（读 SKILL.md 的一次性成本）|

| 任务 | 通过(技能) | 通过(基线) | 技能强在哪 |
|---|---|---|---|
| 搜索 · 3 条 query 找同源 | 5/5 | 4/5 | 基线把 8 个 BLAST 库二进制文件丢进交付目录；技能在临时目录建库 |
| 比较 · 4 基因组 ANI + 同种判定 | 4/4 | 4/4 | 正确性打平；技能快 ~37%、矩阵干净无日志残留 |
| 建树 · 8 条 groEL ML 树 | 4/4 | 4/4 | 打平；两边都诚实标注「序列近乎同一、树不可分辨」未过度宣称 |
| 出图 · 出版级 ANI 热图 | 4/4 | **2/4** | 基线只导屏幕分辨率 PNG、无 600 dpi TIFF；技能恒出 SVG+PDF+TIFF(600dpi,LZW) |

**强势之处**：正确性与认真的基线持平，但在「要可发表 / 要可复现」处拉开差距——① 每次都落 `工具+版本+命令` provenance 脚注（裸跑常漏记）；② 「出版级」图恒定 SVG+PDF+TIFF 600 dpi Nature 风格，基线给的是屏幕 PNG；③ 交付目录只留结果（临时目录建库，不留 BLAST 库 / 原始日志）；④ 调用打磨过的脚本省去重拼 flag，墙钟快 ~26%。

## 触发命中率（击中率）

20 条边界刁钻的路由查询——含「画一棵**已有**的树」该走 report 而非 phylo、「ANI 已算好、画成图」该走 report 而非 compare、整流程 vs 单步、以及 4 条「该谁都不触发」的负样本（写 methods / 润色摘要 / 天气 / 总结 PDF）——6 个描述全部路由正确，**20/20 = 100%**。每个技能另附 `evals/trigger_evals.json`（共 67 条 should-trigger / should-not-trigger 查询），既是触发契约文档，也是回归护栏；装好 API key 后可直接喂官方 `skill-creator` 的 `run_loop.py --eval-set <file>` 做描述自动寻优。

## 安装

**方式一 · 插件市场（推荐）**
```
/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git
/plugin install vivarium@vivarium
/reload-plugins
```
> 用 HTTPS 完整网址，避免无 SSH 密钥时克隆失败。

**方式二 · 脚本（克隆后本地安装）**
```bash
git clone https://github.com/Jason-0409-G/vivarium.git
cd vivarium
bash install.sh            # 把 skills/ 拷进 ~/.claude/skills/
```

## 依赖

分析工具需在 **`bio_tools` conda 环境**里（技能从不自动安装，缺什么会告诉你）：
- QC/注释：seqkit、Prokka、（CheckM2、Flye、eggNOG-mapper、dbCAN —— 可选/重活）
- 比较：FastANI、EzAAI、OrthoFinder、MUMmer4
- 系统发育：MAFFT、trimAl、IQ-TREE、FastTree、PAML(codeml)、PAL2NAL
- 搜索：BLAST+、DIAMOND、HMMER
- 出图：Python(pandas/matplotlib) 或 R(ggplot2/svglite/ragg)

## 设计原则

- **混合执行**：轻量直接跑、重活生成命令交你跑，不无人值守地跑长任务。
- **绝不自动装包**：缺工具/数据库只提示，由你决定。
- **provenance（每步标注软件版本号）**：每个脚本跑完都打印统一脚注 `=== vivarium-… done === / tool: <名>(<版本>) / command: <精确命令>`——6 个分析脚本与两个出图后端（matplotlib / ggplot2，含各自版本）已全部统一，直接可入方法学。
- **图服务于科学逻辑**：不过度宣称，n=1 不外推。
- **软删除**：不 `rm`，需清理移到 `_deleted/`。
- **弱模型友好（DeepSeek 等）**：每步都是「跑这条确定命令、读它的输出」——分析逻辑全在捆绑脚本里（FastANI/IQ-TREE/BLAST… + 统一 provenance 脚注），模型不需自己拼 flag、不需多步工具编排，所以换到非 Claude 后端（如 `deepseek-v4-pro`，子代理 `deepseek-v4-flash`）也稳。

## 许可

见 `LICENSE`。
