# V1 工具融合进 V2 durable loop —— 配合优化路线图

V2 = V1 那套可变 JSON `run_manifest.json` 的 **durable / 崩溃安全 / 事件溯源替代品**。V1 的 prep/compare/phylo/search/report 脚本通过一个**通用适配层**（`skills/vivarium/vivarium_v2/v1_adapter.py`）作为 durable stage 运行：`run_v1_step` 组 `argv=[bash,脚本,action,--flags]` 交给 `loop.perform_one_step`（真进程 → 验证 → 提交 STAGE_COMMITTED）。V1 脚本**保持独立可用**，所有配合改造都在适配层/harness 或以「新增可选 flag」方式做，默认行为不变。

## 已实施的配合修复

| # | 修复 | 提交 | 影响 |
|---|---|---|---|
| **P0** | **解释器/环境注入（核心）** | `32a0572` | harness 直接 spawn、不激活 conda、继承调用方 env → V1 脚本找不到工具、`plot.py` 缺 pandas 崩溃。`resolve_env()` 把 `<VIVARIUM_CONDA_PREFIX 或 /opt/anaconda3>/bin` 前置 PATH + 选对解释器，harness `Popen(env=)` 透传，`missing_tools` 查注入 PATH。**一处修好全部 5 脚本，V1 零改动。** report:heatmap 现可跑。 |
| **P1** | **`--out` 必须 workspace 相对** | `601cb5b` | 绝对/`../` 的 `--out` 会写到 sealed workspace 外 → commit 成功但 evidence 静默丢失。适配层前置拒绝。 |
| **P0** | **phylo tree 固定 seed** | `d190a49` | IQ-TREE ultrafast bootstrap / FastTree 抽随机 seed → 两次跑 support 值不同 → treefile 字节不同 → durable 恢复非 byte-identical。`phylo.sh` 加 `--seed`（默认 42）传给 iqtree/FastTree。 |

## 工具可用性（本机实测）
- **已装**（能内联跑）：fastANI、mafft、trimal、iqtree、codeml、blastp/blastn/makeblastdb；anaconda python 有 pandas/matplotlib（report）。
- **缺**（走 scaffold/ingest）：seqkit、prokka、EzAAI、nucmer、show-coords、FastTree、orthofinder、diamond、pal2nal.pl。

## 两条路径都已跑通
- **inline**（已装工具）：compare:ani 跑真 FastANI on 真实 Shewanella 基因组 → 提交 ANI 矩阵（`54b2352`）。report:heatmap 跑真 matplotlib 图（env 注入后）。
- **scaffold/ingest**（缺工具/heavy）：用户外部跑、产物放进 workspace，`ingest_outputs.py` 校验非空 → 密封提交，下游无差别读取（`08f1c01`）。解锁 prokka/orthology/IQ-TREE/dN-dS 等。

## 剩余优化路线图（按优先级，均 not-breaking）

来自 5-agent V1 review（`scratchpad`/task `w2k7fre1t`），尚未实施：

1. **确定性（correctness，恢复必需）**
   - CRLF→LF 归一（phylo trimAl 长度守卫按字节计数，行尾差异会改分支）。
   - EzAAI 由 basename 派生 label → 同基因组不同路径产不同字节，需 canonicalize。
   - `mktemp -d` 随机中间目录 → 换 workspace 下固定子目录（compare/search/phylo），恢复可预测。
   - report 避 TIFF（600dpi 栅格化跨字体/库版本非确定）→ 默认 SVG/PDF（矢量稳定）。
2. **中间产物进 seal**：compare（ani/aai/synteny 的 `mktemp -d`）、search（DB 目录）把 raw/中间文件写进 workspace 子目录，崩溃可审计。新增 `--work-dir`。
3. **provenance 落 workspace 文件**：工具名+版本+精确命令目前只进 stderr/stdout（被收进 execution_logs 但不作 payload seal）→ 新增 `--provenance <file>` 写 workspace JSON，供 methods 结构化引用。全部脚本。
4. **`--check`/dry-run 预检**：脚本内验依赖后退 0/1 不做分析，让适配层区分「工具缺失（该 scaffold）」与「工具崩溃（真失败）」。全部脚本。
5. **其余脚本 `--out` 相对校验**：适配层已挡（P1），脚本内也可加固。

## 判断
- **核心配合问题（env 错配）已解决**——这是唯一致命、阻塞全部脚本的问题。
- 剩余项是**加固/确定性**：确定性项在实际跑重工具做 durable 恢复时才显现，优先级次于 env；其余是可审计性/可发现性提升。
- 所有 V1 脚本仍独立可用；适配层是唯一的「配合」代码。
