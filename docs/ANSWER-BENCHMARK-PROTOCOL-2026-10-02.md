# 真实问答三路线评测准备

本轮只完成冻结与无模型 runner，**尚未运行真实答案质量**，没有采用候选、增加预算或写生产。

## 材料与分组

冻结 v14 受控试验的16份来源和24条旧候选，形成32道挑战题：每份来源各一道历史回查题、一道当前有效性题。来源、问题、出处、候选及逐题答案口径只存私有 `evaluation/2026-10-02/`，输出0600。

16份来源都已用于规则开发，全部标为 **challenge**。其中此前称为“新材料”的3份如今也已见过，不能再次作为未见测试。此次 unseen-test 状态明确为 **not_frozen_not_run**。按 conversation 分组，development/challenge/unseen 不允许跨组，后续真正未见来源须另选、另冻结，不能为了凑数量把旧题改名。

既有30道合成验收框架仍保持原来的 development12/test18；它只验证框架，不证明真实质量。新增 runner 的合成自测采用10个虚构会话、30题；这些数据与真实挑战材料分开。

私有契约 v2 在任何真实检索或答案执行前修订了相关性目标：已知模态强化缺陷不列为直接答案目标，部分重叠概括只作支持材料；两条仍保留在24条候选语料里，便于暴露错误检索/使用。原v1及收据保留，不覆盖历史。其余标签仍为 Agent 暂定，不是人工 gold。

## 三路线及公平性边界

- **archive**：实际可见原文索引检索，返回 snippet 与稳定 locator；尚未执行完整原消息扩页。
- **candidate**：实际候选 snapshot/search_page，保留 source_reported/imported_summary 等状态，不能当已核实上下文。
- **combined**：实际 evidence_bundle，可信、候选、原文分组；共享序列化字符预算，保持现有策略，不临时调排序。

默认各路线 max_chars=6000、候选 lexical-v1，可显式选择v2/v3并记录。同源多chunk折叠为一个原文身份，原文与候选两种表示仍是同源，不算独立佐证。组合报告的 ID 顺序为原文后候选分组，并非融合排序；不得用其跨组位置冒充排名优化效果。

这个最小 runner 只物化供答案阶段使用的证据包。原文目前只含有界snippet，后续生成答案前须把原文扩页策略、最大来源数、总输入tokens和失败计量冻结并对三路线一致记账；不能把现有snippet路线称作完整原文问答。

## 执行与结果口径

```sh
python scripts/memory_answer_benchmark.py \
  --contract /private/answer-challenge-v14-frozen-v2.json \
  --output /private/freeze-receipt.json
# 仅隔离本地证据检索；仍不生成答案或调用模型
python scripts/memory_answer_benchmark.py \
  --contract /private/answer-challenge-v14-frozen-v2.json \
  --rehearse --retrieval-mode lexical-v1 --max-chars 6000 \
  --output /private/three-route-evidence.json
```

契约收据绑定来源选择、分组、候选、问题和rubric。runner构建临时SQLite，重放归档和候选、建立可见索引，并调用真实读取函数；不访问线上数据库、不会提炼或确认事实。读取输出保留 `answer=null / answer_judgment=null / answer_judge_status=not_run`，不得称答案正确率已通过。

最终答案质量须另行逐题审阅：内容正确、归属、许可/强制及事实/愿望程度、条件/假设、时间有效性、引用支持和正确弃答。检索命中率与最终答案分开报告。旧挑战成绩用于防退化，未见题独立报告；本轮冻结不是质量批准，也不恢复全量提炼。

## 本轮执行状态

已在临时本地数据库完成32道已见挑战题的三路线证据准备。原文、候选、组合共96个返回均遵守6,000字符预算；最大值分别为5,970、5,991、5,966字符。三路线各32题均有检索返回，包含不能确定当前有效性的题；这不代表能够回答，更不代表正确弃答。最终答案生成与评判仍为 **0 / not_run**，模型请求0，未见测试尚未冻结。私有契约v2、冻结收据和证据报告保留于 `evaluation/2026-10-02/`，公开报告不包含原文或人物信息。
