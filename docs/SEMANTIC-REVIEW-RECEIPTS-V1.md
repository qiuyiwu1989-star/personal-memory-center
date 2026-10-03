# 逐陈述语义复核收据：第三轮离线工具

这项开发补齐人工或独立审阅结果的记录和完整性检查，不替代审阅者判断。工具不调用模型、不连接数据库、不写生产，不改变 `quality_approved`；即使所有标签通过，最多返回 `ready_for_owner_review`。身份、独立性和真实 holdout 均为提交者声明，工具不认证这些声明，也不证明原文或判断为真。

## 冻结、审阅和保存

使用 `scripts/review_memory_semantics.py`。由明确选择的原件及原始 provider 输出建立 package，先冻结再评审。首次仅传 package，生成 `frozen_not_run` 收据；独立评审文件引用原 package 的 SHA256，不得在看过结果后改 rubric、编号、来源或方法。工具能发现冻结哈希不一致，不能证明冻结发生在评审之前，执行过程仍须留痕。

```sh
python3 scripts/review_memory_semantics.py --package "$PRIVATE_PACKAGE" --output "$NEW_FREEZE_RECEIPT"
python3 scripts/review_memory_semantics.py --package "$PRIVATE_PACKAGE" --review "$PRIVATE_REVIEW" --output "$NEW_REVIEW_RECEIPT" --previous "$NEW_FREEZE_RECEIPT"
```

输出路径必须在公开仓库之外，以 0600 权限排他新建；已有收据不能覆盖。可用 `--previous` 保留上一份原始字节 SHA256，形成追加链；它只记录谱系，不认证上一份收据。后续纠正新建收据，不改旧标签。stdout 只有状态、总数和收据哈希，不打印原文及审阅内容。

Package 结构：

| 字段 | 约定 |
| --- | --- |
| `data_kind` / `independent_holdout` | `synthetic_development` 或 `real_holdout`，及显式布尔独立声明；开发集不能声明独立 holdout |
| `method` | 抽取方法的 `version` 与冻结的 64 位十六进制 `sha256`；工具另外记录自己代码的 SHA256 |
| `expected_case_ids` / `cases` | 非空唯一预定编号，案例集合必须完全一致；未执行案例仍保留 |
| 案例 `category` | `owner_decision`、`third_party`、`conditional`、`correction`、`need_vs_plan` |
| 案例 `source` / `rubric` | 原始来源 JSON；五个维度分别写独立审阅问题 |
| 案例 `output` | 原始输出；`execution_status` 为 `completed`、`failed`、`not_run`；生成陈述含唯一 `claim_id` 与 `statement` |
| `output.delivery_status` | `accepted_candidate`、`rejected`、`not_attempted`、`not_run`；拒绝必须另有 `delivery_failure` |

**生成状态与交付状态是两件事**。`execution_status=completed` 只指 provider 生成完成，不意味着 pipeline 接受、正式写入或可信。比如旧 case5 provider 有候选、随后 `source_span_contract` 拒绝：应保留 generated claims，并列写 `completed / rejected / source_span_contract`，可以复核生成候选的语义，但不能把它当作已交付的成功结果。失败生成／未生成仍为 `not_run`，不把没有输出当作合理零候选。

审阅 JSON 包含：

- `package_sha256`：冻结 package 的哈希。
- `reviewer`：`id`、`kind`（`human`、`independent_agent`、`synthetic_test`）、显式 `independent` 布尔声明。
- `cases`：逐 `case_id` 的案例整体 `dimensions` 和逐 `claim_id` 的 `claims[].dimensions`。案例整体也必须复核零候选是否合理及重要遗漏，避免“没有候选所以自动通过”。
- 每个 `dimensions`：`speaker`、`commitment`、`condition`、`time`、`source_alignment`，每维为 `{ "verdict": "passed|failed|ambiguous|not_run", "rationale": "依据及边界" }`。评过的维度必须说明理由。

缺案例、缺陈述评分或缺维度均保留 `not_run`，绝不缺省通过；未知／重复编号和维度会拒绝。`ambiguous` 不算通过。每个案例保留来源、输出、rubric 的分别哈希，整个输入及评审标签也分别冻结。哈希验证只是字节内容一致，引用对应也不等于语义蕴含、观点归属或当前有效性。

只有完整、五类覆盖、声明独立的真实 holdout、声明独立人工逐项通过、且 pipeline 已接受候选，工具才标 `ready_for_owner_review`；独立 Agent 标签始终是暂定评审，不能直接放行。所有结果 `quality_approved=false`、`production_gate_changed=false`，没有连接预算或队列。`accepted_candidate` 也不是 verified。

## 开发探针和真实评测分开

第二轮 17 个合成探针是固定开发回归，检查词法提示和守卫行为，没有真实 provider 输出，也不是独立 holdout。新工具不会将那 17 个确定性通过转为语义通过。已有 `evaluate_memory_acceptance.py` 继续负责检索／最终回答评测；本工具仅补充抽取陈述的五维审阅收据，没有新平台或服务。

本轮新增 10 个明确合成测试，包含未评维度、失败生成、零候选、来源变化、重复编号、暂定 Agent 评审、原件与交付失败并列，以及追加且不可覆盖的私有收据。测试中的 `real_holdout` 仅测试字段门槛，不是实际真实 holdout。没有读取私有原件、实际评分旧 case5、运行模型或新增真实评测结论。

下一步应选择与开发隔离的真实正／负例并冻结来源、方法和 rubric，实际生成、独立复核及用户批准分开推进。这份工具不测召回率，也不能证明最终回答质量，现有真实失败／未决结论继续保留。
