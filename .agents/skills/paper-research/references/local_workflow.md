# 本地论文工具流程

项目根目录是本 Skill 目录向上三级，即包含 paper_research、data、prompts 的文件夹。Python 解释器优先使用该项目的 .venv；不要依赖固定盘符。
这是项目内技能，脚本需要同一项目的运行包、数据和模型缓存。迁移时保留项目结构，单独复制 SKILL.md 并不能带走整个应用。
以下命令在项目根目录运行，路径中的 python 表示该环境的解释器。

## 材料准备

已有语料索引位于 data/index/corpus.json。增加论文可使用本地网页上传；原始 PDF 保存在 data/raw，原页文字保存在 data/processed。
离线 Embedding 模型位于 models/hf_cache。建库命令：

```text
python -m paper_research build
```

脚本保留 raw_text、页码和字符位置。超长 token 窗口会进一步拆分。PDF 没有文字时会明确失败；没有实现 OCR。

## 按范围检索

```text
python -m paper_research search --query "研究问题" --method hybrid --scope abstract --doc-id qasper --output output/skill_search.json
```

--scope abstract 只允许已识别摘要内的片段；没有可信摘要边界时，不回退全文。
多篇论文重复 --doc-id。省略则在索引中全部论文检索。中文稀疏匹配使用显式术语扩展；也可用 --lexical-query 指定英文检索词。它不是完整翻译系统。

混合检索为 BM25 与 E5 两路排序，通过加权 RRF 融合。结果包含两路分数、排名和索引校验和。不要把 RRF 分数或余弦相似度解释为答案置信度。

## 由宿主生成回答

```text
python -m paper_research research --question "原始问题" --scope abstract --doc-id qasper --mode packet --output-dir output/skill_packet
```

读取 evidence_packet.json 中的原文、sources 和 evidence_units。只把能支持结论的 U 编号写入草稿：

```json
{"answers":[{"question_id":0,"status":"supported","answer":"根据材料形成的中文结论","citations":"U1"}]}
```

信息不足时使用 status=insufficient、citations=""。多问题 question_id 从 0 顺序编号。
使用 scripts/assemble_report.py 的 packet、draft、output 三个参数，回填原文、来源和位置；再运行 validate_report.py。
这是内部草稿格式，最终给用户的 JSON 仍遵守 output_format.md。

## 独立 Agent 模式

省略 --mode packet 即使用已配置的 Qwen 服务。它运行 LangGraph，并将候选、草稿、最终报告、事件轨迹和调用用量保存到任务目录。
接口失败会报错，不伪装成“论文信息不足”。引用或语义审核两轮未通过时，最终报告会保守返回不足，并保留失败原因。
