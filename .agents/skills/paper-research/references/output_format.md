# 论文调研结构化输出规范

当用户要求 JSON 输出时，使用本规范。

JSON 中的字段名保持英文，回答内容默认使用用户的语言。

## 顶层结构

每次任务的结果包含五个字段：

| 字段 | 内容 |
|---|---|
| material_scope | 本次实际使用的材料范围 |
| answers | 各个问题的回答 |
| evidence | 支持回答的证据 |
| sources | 本次使用的材料来源 |
| limitations | 尚未确认的信息和材料限制 |

## 回答状态

answers 中每个回答都包含 status，取值为：

- supported：材料明确支持这个回答。
- inferred：回答包含基于证据的推断，需要在 answer 中说明推断过程。
- insufficient：材料不足以回答。
- conflicting：已有材料提供了相互冲突的信息。

supported 和 inferred 应关联支持它们的证据。
conflicting 应关联存在冲突的证据，并解释冲突。
insufficient 可以使用空的 evidence_ids 列表。

## JSON 结构示例

下面的内容只展示字段与层次。
实际执行时，将示意文字替换为当前任务的真实内容。

```json
{
  "material_scope": "本次实际读取的材料范围",
  "answers": [
    {
      "question": "用户提出的问题",
      "status": "supported",
      "answer": "根据当前材料得出的回答",
      "evidence_ids": ["E1"]
    }
  ],
  "evidence": [
    {
      "evidence_id": "E1",
      "source_id": "S1",
      "kind": "quote",
      "text": "从当前材料摘录的简短原文",
      "location": "实际可确认的章节或段落位置"
    }
  ],
  "sources": [
    {
      "source_id": "S1",
      "uri": "实际来源链接或本地文件路径"
    }
  ],
  "limitations": []
}
```

## 字段规则

### answers

- 每个用户问题对应一个回答。
- evidence_ids 保存证据编号，不直接存放证据全文。
- 信息不足时，answer 说明缺少什么信息。

### evidence

- evidence_id 在本次结果中唯一。
- source_id 对应 sources 中存在的来源。
- kind 使用 quote 或 paraphrase。
- quote 表示原文摘录，text 应与实际读取的原文一致。
- paraphrase 表示转述，text 应准确保留原意。
- location 使用实际可确认的位置。
- 无法确认页码时，使用章节或段落位置。

### sources

- source_id 在本次结果中唯一。
- uri 使用实际访问的网页链接或实际读取的本地文件路径。

### limitations

记录影响回答的信息缺失、读取失败或比较限制。
没有需要说明的限制时，使用空列表。

## 输出前检查

- JSON 能被正常解析。
- answers 引用的证据编号都存在于 evidence。
- evidence 引用的来源编号都存在于 sources。
- 回答状态与材料充分程度一致。
- 原文、数字和引用位置已经核对。