# Vivarium V2 Tasks 1–6 独立审计报告

审计对象：codex 编写的 Vivarium V2（持久化、事件溯源的生物信息学工作流引擎）Task 1–6。
审计基线：仓库 HEAD = `c062823`（提示中的 `5d12e1c` 是其父提交，两者仅差一个 docs 文件，代码字节一致，审计有效）。
测试状态：`python3 -m unittest discover -s tests/v2` = **137/137 通过**（已复跑确认）。
说明：本人已对最严重的若干发现（task3b-1、recovery-1/2、task4a-1、task5-1、recovery-3、task3b-4/register_run）逐一回查了源码，结论与各领域审计一致。

---

## 1. 总体结论

**判定：暂不合并（Do NOT merge to master）。**

理由如下：

1. **存在多个已确认的 critical 缺陷，且都由“合法输入”触发，而非对抗性构造。** 至少四个 critical 问题会导致提交授权被伪造、或使 store 永久不可恢复：
   - `task4a-1` / `task5-1`：`prepare_commit` 直接用调用方请求里的 digest **合成**整条提交授权链（validator report / checker review / quorum / completion proof），并把 `outcome` 硬编码为 `"success"`（`project.py:657`）。从未运行隔离的 Validator/Checker 角色，也从未在真实证据切面上跑冻结分类器。这**彻底击穿**了整个 Maker/Checker 隔离与 completion 分类机制存在的意义。
   - `task3b-1`：`STAGE_COMMIT_ABORTED(VALIDATOR_REPORT_INVALID / CHECKER_REVIEW_OR_QUORUM_INVALID)` 中止后，旧的 validator report / review / quorum 头**从未被清除**，可被原样重放直接走回 `COMMITTING`，跳过规范强制的重新评审/重新法定。
   - `recovery-1` / `recovery-2`：同一已提交对象上两个 post-commit observation、或两个上游对一个下游 run 的并发 recheck，会让 run-validity reducer 抛 `IntegrityError`；由于账本 append-only，`recover()`/`federate()` 此后**永远失败**——store 被永久毒化，这是规范 §7.4.2 明确承诺支持的正常并发场景。

2. **审核过程不满足代码库自身的门禁标准。** Task 1–6 的“审查轮次”全部是 codex 的**自审**（所有提交同一 git author/committer，无 Reviewed-by trailer；唯一真正的独立对抗审查只针对**设计文档**，且该文档明说“Production implementation has not started”）。规范 §18.3 明确“作者自审不能代替独立复审”，§18 line 2573 明确设计 PASS “不代表实现已正确”。Task-11 Step 7“请求独立代码审查”复选框未勾选，验证记录文件不存在。因此“0 Critical / 0 Important”的实现级声明**无独立背书**。

3. **测试全绿≠正确。** 上述 critical 缺陷所在路径正是测试覆盖的空白：没有任何测试构造 V2 fence、伪造授权链、abort-then-replay、双 observation/双上游 recheck、或写侧 intake-blocker 违规。137 个测试全绿恰恰是因为它们从未证伪规范的核心承诺。

**结论：必须先修复全部 critical（以及阻断合并的 major）缺陷、补齐相应证伪测试、并完成一次真正的独立代码审查，方可考虑合并。**

---

## 2. 确认的问题（按严重度排序）

仅列出 **CONFIRMED** 及实质性 PLAUSIBLE 的发现。REFUTED/not_a_bug 的发现共 **3 个**已剔除（task3a-4「单例 smoke 测试」REFUTED、task6-1「未撤销 capability」REFUTED、task5-3「agent-only harness exit gate」REFUTED）；标记 `unverified` 的发现（confidence low/medium 未经对抗验证）单列在末尾，不作为合并阻断项。

### CRITICAL（阻断合并）

#### C-1 · `task4a-1` / `task5-1` — 提交授权链由 `prepare_commit` 从调用方请求凭空合成
- **位置**：`skills/vivarium/vivarium_v2/project.py:588-761`（`_resume_preparation`），硬编码 `"outcome":"success"` 在 `project.py:657`；循环校验在 `_validate_commit`（`project.py:861-984`）。
- **问题**：run 处于 `COLLECTING` 时，`_resume_preparation` 会用请求里的 digest 依次写入 `EVIDENCE_BUNDLE_FROZEN`、`COMPLETION_CLASSIFIED{outcome:"success"}`、`COMPLETION_PROOF_RECORDED`、`COMPLETION_SUCCESS_PROVEN`、`VALIDATOR_REPORT_SEALED{validation_outcome:"pass"}`、`CHECKER_ALLOCATED`、`CHECKER_REVIEW_SEALED{review_outcome:"pass"}`、`QUORUM_DECISION_SEALED{quorum_outcome:"pass"}`、`CHECKER_QUORUM_PASSED`。`_validate_commit` 随后“重新解析”的正是本次调用刚写入的这些事件——纯自证。`project.py` 不 import `roles.py`/`evidence.py`/`execution.py`，grep 确认它是全包内 `VALIDATOR_REPORT_SEALED`/`CHECKER_REVIEW_SEALED`/`QUORUM_DECISION_SEALED` 的**唯一**生产者。gate 仅取决于调用方自报的布尔 `completion_success`/`checker_quorum_valid`/`budget_available`。
- **失败场景**：`register_run('run-1', analysis_state='COLLECTING')`（`register_run` 接受任意 state，见 `project.py:319`）→ `prepare_commit(valid_commit_request())`（digest 全部伪造，布尔全 True，从未运行任何 Validator/Checker）→ `complete_commit` 成功追加 `STAGE_COMMITTED`。已端到端复现：一个从未执行任何计算、甚至被 OOM 杀死的 run 可被提交为“已证明成功”。
- **规范**：§7.4 lines 671–672、674、707（sealed review 必须由隔离角色产出，自报成功不计入）；§12.6 lines 2049–2065、2071–2078（只有从证据切面导出的 success 分类才能构建 proof / 进入 VALIDATING）。
- **建议修复**：提交路径**禁止**合成任何授权事件；`prepare_commit`/`complete_commit` 必须从**独立角色 daemon**（Maker/Checker 无写权限的 UID）已封存、内容寻址的持久对象读取 classification/proof/report/review/quorum，并对不存在的封存对象 fail-closed。`outcome` 必须由 `classify_completion()` 在真实 `ExecutionEvidenceCut` 上重算，不得硬编码。

#### C-2 · `task3b-1` — abort 后陈旧 report/review/quorum 头存活并可重放至 COMMITTING
- **位置**：`skills/vivarium/vivarium_v2/_run_replay.py:462-499`（`abort_commit` 处理）；字典声明 `_run_replay.py:68-70`，仅在 `593-595` 被读取，**全程无 `.clear()`**（已 grep 确认）。
- **问题**：`STAGE_COMMIT_ABORTED` reason 为 `VALIDATOR_REPORT_INVALID`（→VALIDATING）或 `CHECKER_REVIEW_OR_QUORUM_INVALID`（→CHECK_PENDING）时，处理器只回退 `analysis_state`，从不清除/失效 `validator_reports`/`checker_reviews`/`quorum_decisions`。由于是同一 active attempt，陈旧头仍满足 `apply_validator_report`/`apply_checker_review`/`apply_quorum_decision` 的全部绑定检查。
- **失败场景**：走完整成功链到 COMMITTING → `COMMIT_PREPARED` → `STAGE_COMMIT_ABORTED(VALIDATOR_REPORT_INVALID)`；reducer 返回 VALIDATING 但仍暴露 `validator_report_heads=[v1]` 等。重放原始 `VALIDATION_PASSED(v1)`→CHECK_PENDING、`CHECKER_ALLOCATED`→CHECKING、原始 `CHECKER_QUORUM_PASSED(q1)`→COMMITTING，全程无任何新的 SEALED 事件。已端到端复现。
- **规范**：§6.1 line 448（“所有旧 report/review/quorum 失效”）。
- **建议修复**：`abort_commit` 对 `VALIDATOR_REPORT_INVALID` 清除该 attempt 的 validator/checker/quorum 头（或标记为已失效并在 apply 处拒绝陈旧头）；`CHECKER_REVIEW_OR_QUORUM_INVALID` 至少清除 review/quorum 头。apply 处应额外要求头产生于“当前评审 episode”。

#### C-3 · `recovery-1` — 同一已提交对象上两个 post-commit observation 永久毒化 store
- **位置**：`skills/vivarium/vivarium_v2/project.py:1334`（`open_recheck` 无条件写 `recheck_scope:"own_stage"`，已确认全库唯一 scope 值）；拒绝点 `_validity.py:290-294`。
- **问题**：两个不同 `observation_id` → 两个不同 `recheck_tx_id`，`inbox_observation` 照单全收；`recover()` 为两者各写一个 `COMPLETION_RECHECK_OPENED(own_stage)`。run-validity reducer 要求第二个并发 OPEN（`len(blockers)>1`）的 guard == `additional_complete_cut_durable`，而 own_stage 产生 `complete_cut_durable`，于是抛 `IntegrityError("additional recheck OPEN has the wrong typed scope")`。因两个 OPENED 已持久且账本 append-only，此后每次 `recover()`/`reduce_run_validity()`/`federate()` 都抛同一错误——store 再也无法恢复、federate 或做检索决策。
- **失败场景**：commit stage on run-1 → `inbox_observation(...,'obs-1')` → `inbox_observation(...,'obs-2')` → `store.recover()` 抛 `IntegrityError`，且第 0/1/2… 次调用全部失败。已复现。这是 §7.4 明确允许的正常场景（“commit 后仍可能到达 completion evidence”）。
- **规范**：§7.4.2 line 718（“后续并发 OPEN 只向 blocker set 加 tx”）；§7.4.5 line 721（100 次恢复不丢/不重复消费 blocker）。
- **建议修复**：`open_recheck` 对同一挂起根的第二个及后续 recheck 必须发出 `recheck_scope:"additional"`（映射到 `additional_complete_cut_durable`）；只有对象**首次**被暂停时才用 `own_stage`。

#### C-4 · `recovery-2` — 规范强制的 descendant diamond（两上游 recheck 汇入一下游）不可归约
- **位置**：`skills/vivarium/vivarium_v2/_validity.py:290-294`（raise 在 292）；schema `state_machine.yaml`（own_stage 的 `analysis_descendant` guard = `downstream_dependency_suspended`）。
- **问题**：下游 run 依赖两个上游 stage，各自 own_stage recheck 时，下游对两次 OPEN 都收到 `downstream_dependency_suspended`。第二次 OPEN 命中 `len(blockers)>1` 分支，硬要求 guard == `additional_complete_cut_durable` → `IntegrityError`。schema 中**不存在** `PENDING_COMPLETION_DEPENDENCY --[downstream_dependency_suspended]-->` 的转换，故第二个独立上游暂停永远无法归约，且无任何 scope 赋值能修复（第二上游 owner 合法地用 own_stage）。
- **失败场景**：child 依赖 stage-up1、stage-up2；commit child/up1/up2；up1 own_stage OPEN（child→PENDING_COMPLETION_DEPENDENCY，blockers={txA}）；up2 own_stage OPEN → `reduce_run_validity(child)` 抛 `IntegrityError`。已在 reducer 级复现。
- **规范**：§7.4.2（line 410、718：descendant 持久累积 `blocking_recheck_tx_ids`，并发 OPEN 只加 tx）。
- **建议修复**：为 descendant 引入独立的“再加一个 blocker”自环转换（`PENDING_COMPLETION_DEPENDENCY --COMPLETION_RECHECK_OPENED[downstream_dependency_suspended]--> PENDING_COMPLETION_DEPENDENCY`，仅向 blocker set 加 tx），并在 reducer 中把“第二个 descendant OPEN”与“第二个 owner OPEN”区分处理。

### MAJOR（强烈建议合并前修复）

#### M-1 · `task1-1` — 兼容性 fence 缺失：legacy `init --force` / `update --status done` 可改写 V2 标记的 run 并 exit 0
- **位置**：`skills/vivarium/scripts/orchestrate.py`（`cmd_init` ~104-113、`cmd_update` ~133-150，均无 marker 检测）。
- **问题**：规范 §15.3 / §16 Phase 0 要求任何 V2 writer 之前，legacy orchestrate 必须检测 `run_format.json`（`format=vivarium.run/v2`）并对所有 legacy 写路径 fail-closed（非零退出、不改动任何 event/head/artifact/projection）。实测对含合法 V2 marker 的目录：`init --force` EXIT=0 并改写 manifest；`update --stage 1 --status done` EXIT=0 并翻转状态。fence 完全未实现。
- **缓解说明**：当前 V2 CLI 是纯 stub，没有任何路径能有机地产出 `run_format.json`，故当下需要手工构造 marker 才能触发，尚非活跃损坏向量。但由于 Task 2–8 的 V2 writer 已入库，Phase 0 前置条件在**顺序上也已被违反**。
- **规范**：§15.3 line 2259；§16 Phase 0 lines 2267-2271；marker at line 596、2258。
- **建议修复**：在 legacy 写路径入口加 V2 marker 检测 + fail-closed；补 §16 line 2270 强制的 digest-unchanged 回归测试。

#### M-2 · `recovery-3` — 未 OPEN 的 post-commit intake blocker 不阻止新 stage commit / handoff（写侧禁令缺失）
- **位置**：`skills/vivarium/vivarium_v2/project.py`（`complete_commit` 986、`append_fixture_event` handoff 分支 272-280）；blocker 仅在 `_federation.py:51-63`（读侧）和 `recover()` 的自动 open 循环被消费。
- **问题**：§7.4.1 要求 blocker 未 OPEN 时禁止 handoff active success、stage commit、新 external operation（即使 work cut 仍显示旧 COMMITTED）。实现只有读侧 `default_retrievable=False`，无任何写侧方法查询 `postcommit_intake_blockers`。已复现：存在未 open blocker 时，`append_fixture_event('handoff')` 返回 `HANDOFF_PUBLISHED`、另一 run 的 `complete_commit` 返回 `STAGE_COMMITTED`。
- **规范**：§7.4.1 line 717。
- **建议修复**：在 `complete_commit`/handoff/新 external operation 入口检查是否存在未 OPEN 的 INBOXED/REQUESTED blocker，若有则 fail-closed。

#### M-3 · `3c-1` — 无关的 locked-policy 变更会 stale 一个独立 run（依赖盲的全局水位 staleness）
- **位置**：`skills/vivarium/vivarium_v2/_validity.py:221-231`。
- **问题**：任一携带 `policy_digest`（仅 `POLICY_LOCKED`）且 != `local.merge_policy_digest` 的 revision action，就把 active attempt 翻为 `STALE_CONTEXT`，**不检查该 run 是否实际依赖该 policy 对象**。`merge_policy_digest` 在 run 创建时冻结为当时的全局 locked policy，故任何后续 `POLICY_LOCKED` 都 stale 掉每个既有 run（含依赖闭包不含该 policy 的 run，`validity_reasons` 为空可证）。这正是规范禁止的“只替换 revision/watermark 而不重做 closure 检查”。
- **失败场景**：run `depends-B`（闭包 {truth:fact-B}）；记录无关 `POLICY_LOCKED` → 状态 COMMITTED→STALE_CONTEXT，`run_validity_slice_root` 改变，而 `validity_reasons` 为空。已复现。
- **规范**：design lines 555、1070、1071、1276。
- **建议修复**：policy staleness 必须走依赖闭包/失效 join——仅当 locked-policy 对象在 run 的冻结闭包中才 stale，而非全局 digest 比较。

#### M-4 · `3c-2` — `relevant_project_validity_input_root` 嵌入全局 `locked_policy_digest`，无关 policy 变更移动每个 run 的 relevant-input root
- **位置**：`skills/vivarium/vivarium_v2/_validity.py:389-404`（尤其 392）。
- **问题**：`relevant_root` 顶层嵌入 `validity.locked_policy_digest`（全局标量），而规范要求该 root 只由 run 冻结依赖可达的 project head/status/invalidation 子集计算。任一无关 `POLICY_LOCKED` 都会改变每个 run（含零依赖 run）的 relevant-input root。此缺陷独立于 M-3（即使 M-3 的 staleness 路径不触发也会发作）。
- **失败场景**：`depends-B` 上记录无关 `POLICY_LOCKED(pol-x)` → 逐依赖子集字节不变，但 `relevant_project_validity_input_root` 与 `run_validity_slice_root` 均改变。已复现。
- **规范**：design lines 555、1046、1276。
- **建议修复**：从 `relevant_root` 移除全局 `locked_policy_digest`；若 run 真依赖某 locked policy，它应作为 DependencyHead 出现在闭包中并由逐依赖循环覆盖。

#### M-5 · `3c-3` — depended-on fact 在 recheck OPEN 与 REFRESH 之间变更，使合法 project 账本对某 run 不可重放（抛 IntegrityError 而非产出 STALE slice）
- **位置**：`skills/vivarium/vivarium_v2/_validity.py:308`（`overlay_transition`）。
- **问题**：run 处于 COMPLETION_RECHECK_PENDING 时若 depended-on fact 变更，head-change join 正确把 effective state 翻为 STALE_CONTEXT；随后合法的 `COMPLETION_PROOF_REFRESHED` 从 STALE_CONTEXT 源触发 `match_transition` 时无匹配转换 → 抛 `IntegrityError`。`reduce_project_cut` 成功（账本完全合法），但该 run 的 federated certificate 永远算不出，阻塞其可用性。errs fail-closed（无伪造），但仍是正确性/健壮性缺陷。
- **失败场景**：STAGE_COMMITTED→COMPLETION_RECHECK_OPENED(own_stage)→FACT_ACTIVATED(depended-on)→COMPLETION_PROOF_REFRESHED；`reduce_run_validity` 在 308 抛 `IntegrityError('event does not match exactly one closed transition')`。已复现。
- **规范**：design lines 1070、1071、1276（staleness 支配 restore，应产出 STALE slice）。
- **建议修复**：当 recheck 期间发生依赖 staleness 时，overlay_transition 应让 staleness 支配（保持/产出 STALE slice），而非对 REFRESH/REVOKE 从 STALE 源硬走 match_transition。

#### M-6 · `task4a-2` — `completion_proof_digest` 从不在 complete-cut 从持久 CompletionProof 对象重派生；无有界最终 completion refresh
- **位置**：`skills/vivarium/vivarium_v2/project.py:986`（`complete_commit`），digest 取自请求 `project.py:537`，写入 STAGE_COMMITTED `project.py:1028`，自证校验 `project.py:964`。
- **问题**：§7.4 step 6 要求 complete-cut 前 Broker 做有界最终 refresh，将 canonical proof body 写入内容寻址存储（file+dir fsync），从持久字节重算 `completion_proof_digest`（“不得只引用内存中的 digest”）。实现无此 refresh，`completion_proof_digest` 逐字取自请求；无任何磁盘 proof 对象支撑。
- **失败场景**：请求提供 `completion_proof_digest = domain_hash(任意)`；提交记录该值为已提交 proof digest，磁盘无对应 proof 对象，事后审计无法从持久字节重派生。已复现（磁盘仅 .artifact / .registration.json，零 proof 文件）。
- **规范**：§12.6 step 6 line 2710（原文 §7.4 step 6 line 710）。
- **建议修复**：complete-cut 前将真实 CompletionProof body 持久化并从字节重算 digest 写入 STAGE_COMMITTED。

#### M-7 · `task4a-3` — `abort_commit` 在 COMPLETION_CLASSIFIED/STAGE_COMMIT_ABORTED 之间非幂等；崩溃卡死事务
- **位置**：`skills/vivarium/vivarium_v2/project.py:1085`（分类追加）、`1107-1112`（abort 追加）；幂等守卫 `_outcome`（`project.py:851-859`）只识别已写的 STAGE_COMMIT_ABORTED。
- **问题**：completion-* reason 时 `abort_commit` 分两次持久追加。若崩溃发生在 COMPLETION_CLASSIFIED 之后、STAGE_COMMIT_ABORTED 之前，重试会追加**第二个**同 `classification_id`，`reduce_run` 抛 `IntegrityError("completion classification IDs must be unique")`，事务永久卡死（既无 ABORTED 也无 COMMITTED）。`recover()` 仅因走非 completion reason `HUMAN_JUDGMENT_REQUIRED` 而侥幸绕开，同时把具体失败降级为通用 ESCALATED。
- **失败场景**：`prepare_commit` → abort 中途崩溃 → 重试 `abort_commit(prepared,'COMPLETION_FAILURE_RETRYABLE')` 抛 `IntegrityError`。已复现。
- **规范**：§7.4 step 1 line 705、line 713（原子单条 ABORTED；重复 tx 返回原结果）。
- **建议修复**：让 abort 幂等——`_outcome` 应识别孤儿 COMPLETION_CLASSIFIED 并从中续做；或将分类+abort 合并为可幂等重入的单步。

#### M-8 · `task4a-5` — 合成路径只能准备单 checker quorum，多 review quorum 不可提交
- **位置**：`skills/vivarium/vivarium_v2/project.py:725`（只用 `review_digests[0]`）；校验 `project.py:968`（比较完整 `review_digests` 元组）。
- **问题**：合成只封 1 条 review，而 `_validate_commit` 要求 sealed reviews 的 digest 元组 == 完整 `review_digests`。故任何 len>1 的请求恒被拒（`IntegrityError`），合法多 checker quorum 无法提交。与 C-1 叠加：quorum 抽象“单可伪造、多不可用”。fail-closed（过度拒绝），无数据损坏。
- **失败场景**：`review_digests` 长度 2 → `complete_commit` 抛 `IntegrityError`。已复现。
- **规范**：§7.4 lines 671-672、707。
- **建议修复**：随 C-1 一并重构提交授权来源（从独立封存的多条 review 读取），使多 checker quorum 可被合法提交。

#### M-9 · `task5-2` — `absence_evidence` 语义与规范倒置；success cut 携带非空 `absence_evidence`
- **位置**：`skills/vivarium/vivarium_v2/execution.py:341`（`_success_authority`），cut 构建 `_cut_from_terminal`/`_agent_only_cut`。
- **问题**：§12.6 line 2023 定义 `absence_evidence[]` 严格为**缺失对象**的 typed 绑定，且 `outcome=success => absence_evidence=[]`。实现倒置：`_success_authority` **要求**存在正向 token（`outputs_quiescent`/`process_exited`/`no_live_tasks`/`capabilities_revoked`）才判 success，且成功 cut 发出非空 absence_evidence。规范 fail-safe（缺 sentinel 的失败必须携带 typed absence 证据）未建模。
- **失败场景**：真实 local/agent success cut 的 absence_evidence 非空，违反 2023；真实失败（缺 sentinel）不经 typed absence_evidence 表达。已复现。
- **规范**：§12.6 line 2023。
- **建议修复**：success 时 `absence_evidence=[]`；用正向的“terminal-success token”另行表达 success 授权；`absence_evidence` 仅承载缺失对象的 typed 绑定。

#### M-10 · `task5-4` — `build_completion_proof` 不强制 per-kind null/非-null oneOf
- **位置**：`skills/vivarium/vivarium_v2/execution.py:438`。
- **问题**：§12.6 line 2067/2076 要求 proof body 字段组合与 execution kind 不一致时在落盘前 hard-fail（agent-only 的 process/local_executor/profile/fingerprint/sentinel 必须 JSON null 等）。实现逐字段从 cut 拷贝，无 per-kind nulling 或校验；合法 agent-only 路径亦发出非空 `sentinel_digest`/`scheduler_fingerprint`/`local_executor_identity_digest`。
- **失败场景**：`complete_agent_only(...)` 产出的 proof 上述字段为非空 sha256（规范要求 null）；手工构造的 agent_only cut 携任意非空 local/scheduler/sentinel digest 也能建 proof，无 `IntegrityError`。已复现。
- **规范**：§12.6 lines 2063、2067、2076。
- **建议修复**：落盘前按 execution kind 强制 null/非-null oneOf，不一致即 hard-fail。

#### M-11 · `task5-5` — `success_grade` 对每个 proof 硬编码为非规范字面量 `"L1"`
- **位置**：`skills/vivarium/vivarium_v2/execution.py:443`。
- **问题**：规范 success_grade 枚举为 `{authoritative_agent_harness, authoritative_local_process, authoritative_accounting, l1_sentinel_fallback, null}` 且须匹配 execution kind。`"L1"` 非合法值，抹除了“权威完成”与“降级 sentinel fallback”（规范特意用 `allow_l1_sentinel_fallback`+finality timeout 门控）的区分。（注意：`roles.py` 的 `QuorumPolicy.success_grade` 用 `{L1,L2}` 是另一概念，合法且无关。）
- **失败场景**：每个 agent_only/local_process success proof 报 `success_grade='L1'`；任何按规范枚举做 provenance/acceptance 的消费者无法区分权威与降级。已观测。
- **规范**：§12.6 lines 2002、2067、2072-2075。
- **建议修复**：按 execution kind 设置正确的枚举 grade，并在 kind/grade 不一致时 hard-fail。

#### M-12 · `task5-6` — local success 授权不要求有效 `sentinel_digest`
- **位置**：`skills/vivarium/vivarium_v2/execution.py:366-372`。
- **问题**：`_success_authority` 的 local_process 分支检查 `process_or_job_ref`、`'process_exited'`、`local_executor_identity_digest`，但**从不**校验 `sentinel_digest`（scheduler_job 分支却要求 `_is_digest(sentinel_digest)`——不对称即证 bug）。§12.6 gate 2 要求 local sentinel 存在且匹配。
- **失败场景**：`kind='local_process', exit_code=0, sentinel_digest='no-sentinel-here'` 等 → `classify_completion` 返回 success，`build_completion_proof` 产出携该非法字符串的 proof。已复现。
- **规范**：§12.6 line 2076 gate 2、2073、2081。
- **建议修复**：local 分支加 `_is_digest(cut.sentinel_digest)`（并与真实 wrapper sentinel 匹配）。

#### M-13 · `task6-2` — `evidence_bundle_digest` 不绑定 code/environment/platform-locale/execution-request/key-material
- **位置**：`skills/vivarium/vivarium_v2/evidence.py:69-88`（`EvidenceBundle.canonical_body`）；被引 `ExecutionEvidenceCut`（`execution.py:196-266`）也不含这些字段。
- **问题**：§5.3/§17.4 要求仅改变 code digest、container/environment、platform/locale、execution request 或 KeyMaterial 任一项时 `evidence_bundle_digest` 必须改变（payload root 可不变）。实现完全省略这些字段，故它们不同却产出相同 bundle digest——绑定该 digest 的旧 validator report/checker review/cache 身份会被跨 code/环境错误复用。
- **失败场景**：payload/logs/writer closure/revocation/cut 相同但 code 或 environment 不同的两次执行产出相同 `evidence_bundle_digest`。已构造确认。
- **规范**：§5.3 lines 226-257；§17.4 line 2443。
- **建议修复**：将 code/environment/platform-locale/execution-request/key-material（或承载它们的 ExecutionIntent digest）折入 bundle canonical body。

#### M-14 · `task6-3` — `namespace_attestation` 只是公开 digest 的纯哈希——可重算，非不可伪造的独立隔离证明
- **位置**：`skills/vivarium/vivarium_v2/roles.py:227-234`（构建）、`358-373`（`decide_gate` 重算校验）。
- **问题**：attestation = `domain_hash(..., {assignment_digest, capability_receipt_digest, capability_namespace})`，三个输入皆公开，无密钥/nonce/隔离探针 receipt。任何人可从公开 digest 重算出字节相同的 attestation，故它对“同一真实 namespace 用两个自报 ID 重贴标签”零防护；L2/L3 双 namespace 独立性仅取决于自报 `capability_namespace` 字符串的诚实。
- **失败场景**：同一真实进程自报两个不同 `capability_namespace` 字符串 + 两个 checker_id → L2 quorum outcome=pass、accepted=2。已用真实 fixture 复现。
- **规范**：§5.4 lines 283、304;§17.4 lines 2448、2452。
- **建议修复**：namespace/isolation 必须由 Orchestrator/harness **分配并观测**（写入 CHECKER_ASSIGNED 事件，逐字校验，Checker 无权自选），并以 Orchestrator 签名/nonce 绑定，而非自证哈希。

#### M-15 · `task6-4` — 证据封存器仅将路径限定在 `store.root`，未限定到 attempt workspace 子树
- **位置**：`skills/vivarium/vivarium_v2/evidence.py:233`（`_secure_read(Path(store.root), relative_path)`）、`166-170`。
- **问题**：`_secure_read` 以 `store.root` 为基做遍历，无“payload/log 必须位于该 attempt workspace（或 Broker-owned execution_logs）子树”的限制。`store.root` 下含 ledgers/、runs/、projections/ 等；任何单链普通文件——含其他 run/attempt 的私有数据或可变 projection——都可被封为候选 payload/log。
- **失败场景**：将 `runs/run-2/.../someone-elses-result.txt` 或顶层 `heads-like-projection.json` 作为 payload_paths 传入 → `seal_evidence_bundle` 无错封入 payload manifest。已复现。
- **规范**：§5.3 line 222；§7.4 lines 669-670;§17.4 line 2437。
- **建议修复**：将封存基路径限定到具体 attempt workspace / Broker-owned logs 子树，拒绝子树外及可变挂载/未声明文件。

### 测试充分性 MAJOR（覆盖缺口，非活跃 bug）

以下四项来自 coverage 领域，均为 CONFIRMED 的“测试充分性”缺陷——生产代码当前可能正确，但规范强制的 §17 oracle 未被证伪，plausible 回归会静默通过。

- **T-1 · `testadequacy-1`**：§17.2 L2366 并发双提交 CAS 竞争从未用真实线程测试（全库唯一多线程测试是 ledger 写锁）。回归窗口（两线程都读 gen=N、都追加 STAGE_COMMITTED）不会被任何现有测试捕获。
- **T-2 · `testadequacy-2`**：§17.2 L2387 Validator/evidence 封存崩溃窗口 fsync-boundary oracle 完全缺失；`evidence.py` 封存路径无任何 fault 注入 hook，无“seal 持久前 Checker assignment=0/commit=0”断言。
- **T-3 · `testadequacy-3`**：§17.2 L2387/L2403 seal-digest 对 validator code/config/env/report-body/revocation 及 13 组件 acceptance_contract 的敏感性未测；丢弃 seal 输入字段的回归会静默通过。
- **T-4 · `testadequacy-4`**：§17.2 L2381 completion 分类器只断言 `!=success`，从不断言精确 outcome（cancelled/preempted 根本未测）。OOM→failure_retryable 之类的错映射不会被捕获（已用 mutant 证实全绿）。

### MINOR / NIT（CONFIRMED，不阻断）

- `task1-2`：缺 §16 L2270 强制的 digest-unchanged 回归测试（与 M-1 绑定）。
- `task1-3`：`test_..._preserves_manifest` 恒真——v2 dispatch 从不写文件，未真正测 fence。
- `task2-1`：recovery 测试从未构造“自洽但链无效”的最终记录，无法证伪“错位尾记录不得被 quarantine”。
- `task2-2`：`durable_replace` 在 `os.replace` 后目录 fsync 失败时不清理，留下未 dir-sync 的目标（内容寻址可自愈，影响低）。
- `task3a-1`：状态机编译期完整性守卫（alias/跨命名空间/开放 source_set）零测试覆盖（已用 mutant 证实守卫可被删除而测试全绿）。
- `task3a-2`：`digest` 字段校验器接受非 hex 体（`sha256:`+64个非 hex 字符被接受）；`event_digest` 家族无下游哈希绑定捕获。
- `task3a-3`：`DUPLICATE_RESUME_STATES` source set 定义但从未引用（死代码，未来漂移风险）。
- `3c-4`：`_validity.py:108` 的 `current_heads` 字典为死代码。
- `3c-5`：byte-identity slice 不变量只对无关 FACT 变更测试，从不对 policy/decision 变更测试（掩盖 M-3/M-4）。
- `recovery-6`：`rollback()` 接受但完全不用 `invalidated_roots` 参数（行为正确但参数误导）。
- `task4a-4`（PLAUSIBLE，medium）：`_validate_commit` 依赖闭包重校验是重言式，检测不到传递边拓扑变化——未经对抗验证，列为待查。
- `task6-7`：evidence 测试的“device”用例被绝对路径守卫拦截，S_ISREG device 分支从未被真正的 in-root 相对路径设备节点触发（覆盖浅）。
- `testadequacy-5/6/7/8/9/10/11`：一系列 §17 oracle 弱覆盖（exactly-1 STAGE_COMMITTED、直接同-tx 重放不变量、revision 100x 非重消费、双独立 canonicalizer、重复 finding 升级、store 级 recheck close-cut、动态 TOCTOU 候选替换）。

### 未验证发现（confidence low/medium，未经对抗验证 — 不作合并阻断，但值得排查）

`task1-4`（legacy --force backup-first 未测）、`task3b-3`（cancel_terminal 仅 RUNNING_REMOTE 源）、`task3b-4`（run genesis analysis_state 无约束——已确认 `register_run` 确实接受任意 state 且无合法入口校验，属真实防御纵深缺口，值得列入）、`task4a-6`（staging 文件名含可变事务计数）、`task4a-7`（observation_id 全局计数器）、`recovery-4`（open-minus-close 枚举缺失）、`recovery-5`（第二 prepared 提交被静默搁置）、`task5-7/8/9/10/11`（安全重启、两遍静止、reducer 信任 outcome、非终结→failure_permanent、claim body 字段缺失）。

---

## 3. 逐 Task 状态

| Task | 实现 | 测试 | 合规判定 | 残留缺口 |
|---|---|---|---|---|
| **1 边界/V1 冻结** | `__init__`/errors/CLI dispatch/legacy 路由 | 4 测试全过 | **不合规** | **M-1 fence 完全缺失**（§16 Phase 0 硬前置违反）；测试恒真/缺 digest-unchanged 回归 |
| **2 canonical events + 账本** | JCS canonical、域分隔哈希、13 字段信封、torn-tail 恢复、fsync/flock | 24 测试全过，G1/G2 独立重算匹配 | **稳健，小缺口** | 恢复测试不覆盖“自洽但链无效”尾记录；`durable_replace` 目录 fsync 失败清理 |
| **3a 状态机** | 数据驱动编译器，205 concrete tuples，编译期守卫，pinned digest | 10+ 测试全过，穷举 cross-product | **稳健，小缺口** | 编译期守卫零覆盖；digest 校验器接受非 hex；死 source_set |
| **3b run-replay** | reduce_run，证据/bundle/proof/report/review/quorum 绑定 | 46 测试全过 | **严重问题** | **C-2 abort 后陈旧头可重放至 COMMITTING**；M-9 相关；operation-level duplicate 死代码（task3b-2 major）；genesis state 无约束 |
| **3c validity/federation** | project/run validity + federate 流水线 | 21 测试全过 | **有隐患** | **M-3/M-4 无关 policy 变更破坏 crown-jewel 不变量**；M-5 recheck 期依赖变更致不可重放；死代码 |
| **4a 提交事务** | init/register/prepare/complete/abort/inbox/recheck/recover/rollback/fork | 15 测试全过（全套 137） | **严重问题** | **C-1 授权链凭空合成**；M-6 proof 非持久重派生；M-7 abort 非幂等卡死；M-8 多 quorum 不可用 |
| **4b 恢复** | post-commit observation、open_recheck、recover 幂等 | 14 测试全过 | **有隐患** | **C-3/C-4 双 observation/双上游 recheck 永久毒化 store**；M-2 写侧禁令缺失 |
| **5 执行** | LocalExecutionBroker、agent-only、冻结分类器、CompletionProof | 11 测试全过 | **有隐患** | **C-1(=task5-1) 提交旁路冻结分类器**；M-9/10/11/12 proof 语义/字段/grade/sentinel 缺陷 |
| **6 证据/角色隔离** | no-follow 封存、EvidenceBundle/ValidatorSeal、Checker quorum | 12 测试全过 | **有隐患** | **M-13/M-14/M-15 digest 绑定不全、attestation 可伪造、路径未限定 workspace**；`decide_gate` 等无包内调用方（未接入提交路径） |

补充：task3b-2（operation-level duplicate `multiple_affected_targets` 路径因合成器硬要求 submission obligation 而不可达，属规范转换的死代码，major，已 CONFIRMED）应计入 3b 缺口。

---

## 4. 测试覆盖评估（§17 oracle）

**真正覆盖（有测试证伪承诺）**：账本 canonicalization G1/G2 硬编码常量（§17.2 L2383）；torn-tail T1/中段损坏 fail-closed（L2359/L2383）；fsync file→dir 顺序 + 写锁贯穿目录同步（§17.5 L2468 协议复用）；prev 引用 event_hash 非 record_checksum；穷举 analysis/obligation/external_client 转换 cross-product 无歧义/跨命名空间（L2401）；abort-reason 闭合映射穷举（L2361）；project-revision oracle（L2385 正向）；fact 变更只 stale 依赖 run（L2399）；提交崩溃窗口 100x 恢复收敛（L2356-2363，但仅 `<=1` 断言）；post-commit inbox 幂等（L2393，但仅单 observation）；local 执行 at-most-once 跨 100 恢复（L2370-2374）；agent-only 单 proof 幂等（L2368-2369）；Checker quorum L1/L2 门控（§17.4 L2447-2452，但仅字面量不同 namespace）；evidence no-follow 静态路径攻击（L2437-2441）。

**弱覆盖（仅更弱属性/浅覆盖）**：
- completion 分类只断言 `!=success`，非精确 outcome（T-4 / L2381）——cancelled/preempted 未测。
- 提交崩溃窗口只断言 `<=1` STAGE_COMMITTED，非“恰 1”（testadequacy-5 / L2363）——fail-stuck 回归可静默通过。
- ledger G1/G2 仅单一 canonicalizer，缺第二独立实现与 0x00/LF/域分隔符变异（testadequacy-8 / L2383）。
- Checker quorum 双 namespace 只测字面量不同的字符串，从不测“同一真实隔离边界重贴标签”（掩盖 M-14）。
- slice byte-identity 只对 FACT 变更测，从不对 policy/decision（掩盖 M-3/M-4）。

**在范围内但缺失**：
- §17.2 L2366 并发双提交 CAS 竞争（T-1）——无任何真实并发测试。
- §17.2 L2387 Validator 封存崩溃窗口 oracle（T-2）——完全缺失，无 fault hook。
- §17.2/§17 L2387/L2403 seal-digest 与 acceptance_contract 敏感性（T-3）。
- §17.4 L2449 重复 finding 签名→升级（testadequacy-9）。
- store 级 recheck close-cut / recover() open-minus-close 分支（testadequacy-10）。
- 动态 TOCTOU 候选替换（testadequacy-11）。

**合理超范围（Task 7-14，不计入）**：HandoffSnapshot、facts/memory 封存与自学习门、生物信息学正确性 fixture、cluster/fake-scheduler、V2 CLI+legacy 迁移、clean-room 独立性等。

---

## 5. codex 审核过程复盘

**性质：全部为 codex 自审，非独立审查。** 证据：`9ac46da..HEAD` 每个提交的 git author 与 committer 均为同一身份（`Jason-0409-G <jg5037@cumc.columbia.edu>`），无任何 Reviewed-by/Co-authored-by/Signed-off-by 区分审查者；“审查轮次”只体现为作者自己的 `fix: close ... review` 提交和自写的 closure 测试。仓库内**唯一**真正的独立对抗审查文档（`docs/superpowers/reviews/2026-07-18-...-adversarial-review.md`）只审**设计文档**，且明确写“Authorized next artifact: Phase A implementation plan only. Production implementation has not started.”——不覆盖任何 Task 1-6 代码。

逐轮：
- **Task 1**：仅 1 个 feat 提交（`57e8ec4`），**无** fix 提交、**无** review-closure 测试。文档标“独立审查 已完成”无任何仓库证据支撑。
- **Task 2**：1 个 review-驱动 fix（`6f5b12c` 目录同步须持锁），闭合于 `test_ledger_recovery.py` +188 行。
- **Task 3**：三轮自审，各自 closure 测试文件（`287b120`→`test_task3_review_closures.py` 22 测试；`83345a6`→`test_task3_rereview_closures.py` 14 测试；`790f245`+`4d51f02`+`6117c0c`→`test_task3_final_critical_closures.py` 5 测试）。文档 §9.5“0 Critical/0 Important/0 Minor”为自证。
- **Task 4**：唯一带显式 C/I finding-ID 分类法的 task（`test_task4_review_fixes.py` 9 测试：C1、I1-I7 + 跨 run 隔离）；fix `403f5bd`、`49f3f34`。文档“Task 4 19/19”已复核属实（3+3+2+2+9）。
- **Task 5**：1 轮自审（`67a8e04`），无专用 closure 文件，fix 折入既有测试。文档 §11.7“0C/0I/0Minor”自证。
- **Task 6**：**无审查轮次**。文档（§12.7/§27.1，提交于 `c062823`，日期 2026-07-19，晚于 5d12e1c）声称 Task 6“暂停/存在未提交草稿/不提交这些草稿”，但 `5d12e1c` **已把** evidence.py、roles.py、support.py 及 12 个 Task-6 测试提交入库（`git cat-file -e HEAD:...evidence.py` 确认 tracked）——文档状态与仓库**事实矛盾**。

**“0 Critical / N/N 测试”声明是否成立？**
- **测试计数声明成立**：已复跑，`Task 5 = 11`、`Task 4 = 19`、`Tasks 1-5 = 125`、全套 `137/137` 全部属实。
- **“0 Critical”实现级声明不成立/误导**：这些是 codex 自审轮次的残留声明，无独立审查者、无提交入库的代码审查记录；本次独立审计恰恰在这些“0 Critical”task 中确认了 **4 个 critical**（C-1 在 4a/5、C-2 在 3b、C-3/C-4 在 4b）。全绿自写测试套件按代码库自身 §18 标准是**必要但明确不充分**的。
- **规范门禁未过**：Task-11 Step 7“请求独立代码审查”复选框未勾，验证记录 `docs/superpowers/reviews/vivarium-v2-phase-a-verification.md` 不存在。

---

## 6. 给用户的建议

**不要合并到 master。** 具体行动：

1. **阻断合并的 critical（必须先修 + 补证伪测试）**：
   - **C-1（task4a-1/task5-1）**：重构提交路径，禁止 `prepare_commit` 合成授权链；改为从 Maker/Checker 无写权限的独立角色 daemon 已封存的持久对象读取 classification/proof/report/review/quorum，并在真实证据切面上重跑 `classify_completion()`。这是最高优先级——它使整个隔离与分类机制形同虚设。
   - **C-2（task3b-1）**：`abort_commit` 对 `VALIDATOR_REPORT_INVALID`/`CHECKER_REVIEW_OR_QUORUM_INVALID` 清除/失效相关 report/review/quorum 头，apply 处拒绝陈旧头。
   - **C-3/C-4（recovery-1/2）**：`open_recheck` 对第二个及后续并发 recheck 发 `recheck_scope:"additional"`；为 descendant 增加“仅加 blocker”的自环转换。修复前，任何双 observation / diamond 依赖都会永久毒化 store。

2. **强烈建议同批修复的 major**：M-1（legacy fence，Phase 0 硬前置）、M-2（intake blocker 写侧禁令）、M-3/M-4（policy staleness 破坏 crown-jewel）、M-6/M-7（proof 持久重派生 / abort 幂等）、M-9~M-12（execution proof 语义/grade/sentinel）、M-13~M-15（evidence digest 绑定 / attestation 可伪造 / workspace 限定）。其中 M-3/M-4/M-14/M-15 涉及核心隔离与不变量，风险高。

3. **补齐 §17 强制 oracle 测试**：并发双提交 CAS 竞争（T-1）、Validator 封存崩溃窗口（T-2）、seal-digest/acceptance-contract 敏感性（T-3）、精确 completion outcome（T-4）、exactly-1 STAGE_COMMITTED、双 namespace 重贴标签、slice 对 policy 变更的 byte-identity。

4. **完成一次真正的独立代码审查**（superpowers:requesting-code-review 或等价的 fresh 隔离审查者），并落地 Task-11 Step 7 的验证记录——这是代码库 §18 自身的门禁要求，当前完全缺失。

5. **修正文档事实错误**：Task 6 的“未提交草稿/不提交”状态与仓库不符（drafts 已入库、12 测试全过）；`docs` 中“独立审查 已完成”的勾选在无独立审查证据前应撤回。

**底线**：测试全绿 137/137 是好的起点，但本次独立审计在 codex 自审声明“0 Critical”的 task 中确认了 4 个由合法输入触发的 critical 缺陷（含永久毒化 store 与伪造提交授权），以及 15 个 major。在 C-1~C-4 修复并经独立审查前，这套代码不安全，不能合并。
