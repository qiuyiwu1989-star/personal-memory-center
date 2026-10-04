# 真实质量评测的冻结与回执绑定 · 2026-10-04

新增 `evaluation_freeze.py` 与 `scripts/evaluate_memory_trial_binding.py`，用于离线检查试跑产出和评审是否对应同一份原件、方法、提示与模型配置。它不调用模型、不修改数据库或预算，也不批准质量或恢复队列。

## 本轮解决

每个 case 冻结 source_sha256、method_version、prompt_sha256、model_profile_sha256；模型配置摘要只包含非敏感配置，不包含 key。评审绑定完整产出 claims 与冻结 case。原件、配置或产出变化后，旧评审被判为失效，必须重新核对。

检查语义支持、归属、时间、范围、长期价值及覆盖维度的显式评审。正例不允许以空产出通过；确实不应产生记忆的负例必须预先显式标记。独立性未知、缺样本、重复产出、缺评审、预算超限或未知用量都会阻断。未知用量保留该尝试的预留，不当作免费调用。

这里的费用合计是离线报告检查，不代替生产账本预留或结算。试跑真正调用前仍需在生产共享账本中设置并预留有限预算。holdout_independence 的 verified 是外部声明，本工具不能自行证明评测者独立；报告明确标记这一限制。

## 使用

输入是仓库外私有 manifest JSON（cases、token_limit、holdout_independence）和 runs JSON 列表。每个 run 包含冻结字段、claims、usage，以及 review；review 的 binding_sha256 由 `review_binding(run, case)` 计算。这个摘要绑定评审对象，不是评审人签名或真实性证明。

```sh
python scripts/evaluate_memory_trial_binding.py \
  --manifest PRIVATE_MANIFEST.json \
  --runs PRIVATE_RUNS.json \
  --output PRIVATE_NEW_RECEIPT.json
```

输出文件必须在仓库外，0600 创建，拒绝覆盖已有文件。标准输出只有状态、费用合计和未知次数，不打印记忆正文或私人 case 标识。阻断返回退出码 2。

即使离线检查通过，也只返回 ready_for_quality_decision；quality_approved 与 production_dispatch_enabled 始终为 false。空候选、字面覆盖、附件下载或工程测试都不能单独批准真实记忆质量。

## 验证与边界

8 项合成测试通过：冻结对象变化、旧评审失效、未知预留、费用超限、空正例、显式负例、独立性/覆盖缺失、CLI 私有权限与拒绝覆盖。

本轮没有新真实模型产出或盲测结果，没有修改试跑预算。长文继承仍是离线复核协议，当前 worker 不接受它；下一步是经原件核对后构建兼容的有界模型请求、冻结小批试跑材料、配置有限评测预算并独立评分。
