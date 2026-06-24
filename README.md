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
- **provenance**：每步记录工具+版本+精确命令，方法学就绪。
- **图服务于科学逻辑**：不过度宣称，n=1 不外推。
- **软删除**：不 `rm`，需清理移到 `_deleted/`。

## 许可

见 `LICENSE`。
