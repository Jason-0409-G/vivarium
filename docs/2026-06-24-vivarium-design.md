# vivarium — 设计文档（spec）

> 日期 2026-06-24 · 作者 Jian Gao
> 状态：**设计已确认，待用户复核此 spec → 转 writing-plans**
> 配套品牌：与 `scriptorium`（research-to-paper）并列的独立仓库/marketplace。

---

## 1. 定位与目标

vivarium 是一个 **Claude Code 插件**（独立 marketplace `vivarium`），做**本地比较基因组分析工作流**。它把用户在 `bio_tools` conda 环境里的比较基因组工具链，包装成一个"伞型协调器 + 可单用子 skill"的体系，**混合执行**：轻量分析直接跑、重/长任务生成脚手架命令交用户跑、结果回来解读。

**一句话**：给 vivarium 几个基因组 + 一个目标，它规划并跑通比较基因组流程，产出图/表 + 方法学就绪的记录；每一步也能单独触发。

## 2. 范围（边界）

**覆盖（in scope）**——比较基因组/序列分析工具箱：
- QC + 组装 + 完整度：Flye、CheckM2、NanoPlot
- 注释：Prokka、eggNOG-mapper、dbCAN
- 直系同源 / 泛基因组：OrthoFinder
- 物种界定：FastANI、EzAAI（ANI/AAI）
- 系统发育：MAFFT、trimAl、IQ-TREE
- 选择压：PAML（codeml）、PAL2NAL
- 共线性：MUMmer4
- 序列搜索：BLAST+、DIAMOND、HMMER
- 蛋白结构：AlphaFold（server/scaffold）
- 出图 + 表 + 方法学小结

**不覆盖（out of scope，本期）**：RNA-seq 差异表达、变异检测、宏基因组分箱、单细胞等。范围若扩，后续另起子 skill，不在本 spec。

## 3. 架构

伞型 `vivarium` 协调，5 个子 skill 干活。每个子 skill 自包含、能单用、也能被伞型串起来。

### 3.1 仓库结构（照搬 scriptorium 手感）
```
vivarium/
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── skills/
│   ├── vivarium/SKILL.md          伞型协调器
│   ├── vivarium-prep/SKILL.md     QC + 组装 + 注释
│   ├── vivarium-compare/SKILL.md  直系同源 + ANI/AAI + 共线性
│   ├── vivarium-phylo/SKILL.md    比对 + 建树 + 选择压
│   ├── vivarium-search/SKILL.md   BLAST / DIAMOND / HMMER
│   └── vivarium-report/SKILL.md   出图 + 表 + 方法学
├── scripts/        共享 helper（runner、版本记录、QC 门、manifest 读写）
├── templates/      参数模板 + 方法学样板
├── docs/           本设计文档 + 用户手册 + 安装说明
├── install.sh / install.ps1
├── README.md / README.en.md
└── tests/          玩具数据 + 测试 runner
```

### 3.2 子 skill 职责 / 输入 / 输出 / 工具

| 子 skill | 输入 | 干什么 | 主要工具 | 输出 |
|---|---|---|---|---|
| `vivarium-prep` | 原始 reads 或 基因组 FASTA | QC、组装、完整度、基因/功能注释 | Flye, CheckM2, NanoPlot, Prokka, eggNOG, dbCAN | 注释好的基因组（GFF/FAA/FFN）+ 功能表（COG/KEGG/CAZy）|
| `vivarium-compare` | 多基因组的蛋白/CDS + 基因组 FASTA | 直系同源群、ANI/AAI 矩阵、共线性 | OrthoFinder, FastANI, EzAAI, MUMmer4 | orthogroups、ANI/AAI 矩阵、共线性图数据、独有/共有基因清单 |
| `vivarium-phylo` | orthogroup 序列 或 标记基因集 | 多序列比对、修剪、建树、dN/dS 选择压 | MAFFT, trimAl, IQ-TREE, PAL2NAL, PAML(codeml) | 比对、树文件(.treefile)、bootstrap、ω/LRT 汇总 |
| `vivarium-search` | 查询序列 + 库 | 序列相似搜索 / 结构域搜索 | BLAST+, DIAMOND, HMMER | 命中表（带 e-value/identity/coverage）+ 解读 |
| `vivarium-report` | 各阶段 manifest 产物 | 出版级图、表、方法学段落 | matplotlib / R | Fig/Table 文件 + methods.md（含工具版本+命令）|

### 3.3 伞型协调器（`vivarium`）
- 接高层目标（"比较这 N 个基因组" / "建系统发育" / "基因 X 受不受选择"）+ 输入。
- 把目标映射成一条**分析 DAG**（示例：比较基因组 → prep(注释) → compare(同源+ANI) → phylo → report）。
- 在 **run workspace** `vivarium_run/<时间戳>/` 下分阶段存产物 + 一份 `run_manifest.json`。
- 按序调子 skill，靠 manifest 传产物；遇重活暂停、交脚手架命令、用户跑完后续接。
- 不发明分析结论；只规划、跑、串、收。

## 4. 数据流 与 run manifest

- 输入：基因组/CDS/蛋白 FASTA，或原始 reads（走 prep）。
- 工作区 `vivarium_run/<timestamp>/`：每阶段一个子目录 + 顶层 `run_manifest.json`。
- 每阶段从 manifest 读上游产物、写自己的产物与状态。
- 终态：图/表 + 自动起草的 methods 段（从 manifest 生成）。

**`run_manifest.json` 字段（草案）**：
```jsonc
{
  "run_id": "<timestamp>",
  "goal": "compare-genomes",
  "inputs": [{"name": "...", "path": "...", "type": "genome|cds|protein|reads"}],
  "env": {"conda": "bio_tools"},
  "stages": [
    {
      "skill": "vivarium-prep", "status": "done|scaffolded|failed",
      "tool": "prokka", "version": "1.15.6",
      "command": "<exact cmd>",
      "outputs": [{"name": "...", "path": "..."}],
      "qc": {"gate": "checkm2_completeness", "value": 99.1, "pass": true},
      "log": "<path to stage log>"
    }
  ]
}
```
> manifest 既是数据流载体，也是**可复现/方法学**的单一真相源。

## 5. 混合执行机制（共享 runner）

`scripts/` 下一个 runner helper，逻辑：
1. **查工具**：在 `bio_tools` 里检测目标工具是否存在（`which` / `--version`）。缺 → 报错并告诉用户装什么，**绝不自动 install**（用户铁律）。
2. **轻/重判定**：按工具 + 输入规模分类。
   - **轻**（直接跑，带超时+日志）：单基因组 Prokka、FastANI、小规模 MAFFT、BLAST/DIAMOND 小查询、EzAAI。
   - **重**（生成脚手架 `.sh`，不替跑）：Flye 组装、多基因组 eggNOG、大 IQ-TREE（含 bootstrap）、PAML、AlphaFold。
   - 阈值（基因组数 / 序列数 / 预估时长）可配置。
3. **轻量**：直接 `bash` 跑，stdout/stderr 进 stage 日志，查退出码。
4. **重活**：写一个可直接执行的 `run_<stage>.sh`（精确命令 + 建议资源/线程 + 提交方式），状态记 `scaffolded`，提示用户跑。
5. **collect**：用户说"跑完了" → runner 把输出文件登记进 manifest，状态转 `done`，继续下游。

## 6. 错误处理 / 质量门

- **前置检查**：缺输入文件 / 缺工具 → 清晰报错，不自动装。
- **每次跑**：捕获 stdout/stderr 进日志、查退出码、失败给日志尾 + 可能原因。
- **QC 门**（不达标就停下报）：
  - 组装后 → CheckM2 完整度/污染阈值
  - 比对后 → trimAl 保留列比例
  - 建树 → bootstrap/SH-aLRT 支持度
  - 注释 → CDS 数 / 注释率 sanity check
- **多工具共识**：CAZy 走 dbCAN **≥2 工具共识**（继承用户项目规范），写进 report 的 methods。
- **可复现**：每条命令 + 工具版本写进 manifest；版本与 templates 里 pin 的预期不符 → warn。
- **软删除**：任何"删除"走项目 `_deleted/`，禁 `rm`（用户铁律）。

## 7. 测试

- **每个子 skill**：小玩具数据（2–3 个迷你基因组 / 玩具序列）+ 期望输出检查（跑通 + 产物存在 + 数值 sane）。
- **伞型**：玩具数据端到端 smoke test（迷你基因组 → 全流程 → report）。
- **重工具**：CI 不真跑——只验**脚手架 `.sh` 命令正确**（命令串、参数、路径），不验 AlphaFold/PAML 真跑过。
- `tests/` + 一个测试 runner，照 scriptorium。

## 8. 贯穿全局的原则（继承用户严谨实践）

- 工具版本 + 精确命令**全程记录**（方法学就绪）。
- 多工具共识（如 CAZy dbCAN ≥2）。
- 合理默认，但**关键参数透明**、可覆盖。
- **绝不自动装包**——缺工具只提示用户。
- **软删除**（`_deleted/`），禁 `rm`/`git clean`。
- 产物**集中在 run workspace**，不乱撒。
- 反 overclaim：报事实数据，解读与结论分开，不外推。

## 9. 打包 / 分发

- 独立新仓库 `~/Desktop/vivarium/`，结构见 §3.1。
- `.claude-plugin/marketplace.json` + `plugin.json`（照 scriptorium）。
- 安装：`/plugin marketplace add https://github.com/Jason-0409-G/vivarium.git`（**用 HTTPS 完整网址**，避免无 SSH 密钥时失败——scriptorium 踩过的坑）+ `install.sh`/`install.ps1` 本地装。
- README 中英双版 + docs 用户手册。

## 10. 待定 / 后续决定（不阻塞实现计划）

- 轻/重阈值的**具体数值**（基因组数、序列数、预估时长）——实现时给保守默认，可配置。
- AlphaFold 走 server 的具体对接方式（本期只脚手架 + 指导，不深做）。
- run workspace 默认落在**当前目录**还是固定 `~/vivarium_runs/`——实现时定，倾向当前目录下 `vivarium_run/`。
- report 出图用 **Python 还是 R**——两者都留接口，默认 Python（matplotlib），重图可切 R。

---

**下一步**：用户复核本 spec → 通过后转 `writing-plans` 出分阶段实现计划（建议先做 `vivarium-search` 或 `vivarium-prep` 作为第一个可跑通的纵切片）。
