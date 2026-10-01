# 记忆提炼正反例与漏记验收

本验收检查候选质量，不能替代事实核实、当前有效性审查或用户确认。公开案例全部为合成材料，真实材料、输出和逐项复核保存在私有评测目录。

## 先定义应保留与应排除，再看输出

每份材料预先建立 `sample_index`、`required_facts`、`forbidden_facts` 三项。每个事实带稳定 `id` 和文字标准。身份更正、长期边界、项目关键决策及理由、明确配置属于正例；即时命令、助手草稿、稿件主人公经历和重复原则属于反例。旧状态必须明确其失效，不得变成当前状态。

合成验收集位于 `tests/fixtures/memory-acceptance-synthetic.json`，覆盖上述情形。七项配置案例同时包含临时写作命令，用于检查分流是否连配置一起丢弃。复述同一原则必须去重，但出处应保留。

## 逐项复核协议

调用 `suite_gate(expected_ids, runs, version, max_output_tokens, acceptance_cases=cases)`。每个 `run` 提供 `claims`（或 `plan.claims`），以及原有五个语义维度复核。额外提供：

```python
run['review']['acceptance'] = {
    'required_matches': {
        'configuration': {
            'verdict': 'pass',
            'claim_indices': [0],
            'reason': '逐项核对来源，七个配置项均完整且适用项目明确',
        },
    },
    'forbidden_checks': {
        'command': {'verdict': 'pass', 'reason': '未将本次写稿命令保存为长期偏好'},
    },
    'no_unexpected_claims': {'verdict': 'pass', 'reason': '逐条核对，均属于验收范围'},
    'no_duplicate_claims': {'verdict': 'pass', 'reason': '无同义判断重复'},
}
```

索引从零开始。每个必须保留事实要映射到存在、正文与引用均非空的候选，并写明支持依据。配置信息要逐项核对；仅提到“有七个智能体”不能视为七项配置完整。仅有出处存在也不能证明概括正确。禁止项逐项检查，无多余候选、无重复也分别检查。

## 关卡含义

- `acceptance_pending_cases`：缺少清单、事实匹配、复核依据或反例检查。
- `omission_cases`：明确判定漏提，或者索引无效、输出为空却声称正例通过。
- `acceptance_failed_cases`：禁留项混入、重复或额外不当候选。
- 同一版本、输出上限、材料完整覆盖及原有语义维度仍须通过。

全通过只得到 `ready_for_owner_quality_decision=true`；`quality_approved` 与 `production_dispatch_enabled` 始终为 false。不能由此自动恢复生产。此关卡防止未审漏记与空结果骗过正例验收；复核者的语义判断本身仍需抽查。

运行：`python -m unittest discover -s tests -p 'test_memory_acceptance.py' -v`。测试验证协议防护，不是模型质量得分。真实难例仍需同版本实际提炼与逐项复核；固定难例组结果不能推断全量准确率。
