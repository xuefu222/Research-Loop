# Research Loop · 论文研究与方案审查

Research Loop 使用 LangGraph 编排研究提案、证据审查与反馈修订。提案和审查分别由 Deep Agents 执行，按需使用 BM25 与 E5 混合检索补充本地论文证据。仓库还包含 Paper Research 论文问答工作台，使用 FastAPI 和 Vue 3。

[项目架构与复跑示例](docs/RESEARCH_LOOP.zh-CN.md) · [Research Loop 面试准备手册](docs/RESEARCH_LOOP_INTERVIEW.zh-CN.md) · [论文问答工作台交付报告](docs/PROJECT_REPORT.zh-CN.md)

[Research Loop 科研验证 Skill](.agents/skills/research-loop/SKILL.md) 用 LangGraph 编排提案和审查，由两个 Deep Agent 分别读证据，符合条件时执行小试并生成报告。[运行契约](.agents/skills/research-loop/references/run-contract.md) · [代码对照与复跑示例](docs/RESEARCH_LOOP.zh-CN.md)

## 直接运行

在仓库根目录打开 PowerShell。新环境先按下方「从源码复现」安装依赖并建立索引。

```powershell
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research serve --port 8765
```

打开 [本地工作台](http://127.0.0.1:8765)，API 文档位于 [本地 API 文档](http://127.0.0.1:8765/docs)。服务默认只监听本机。

使用模型时，将 `config/model.example.json` 复制为 `config/model.local.json` 并填写服务地址、模型和密钥。也支持 `MAIN_BASE_URL`、`MAIN_MODEL`、`MAIN_API_KEY` 环境变量。本地配置文件已加入 Git 忽略规则。

## 独立命令

```powershell
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research search --query "QASPER 有多少问题和论文？" --doc-id qasper --scope abstract --method hybrid
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research research --question "QASPER 有多少问题和论文？" --doc-id qasper --scope abstract
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research research --question "QASPER 有多少问题和论文？" --doc-id qasper --scope abstract --mode packet
```

packet 模式只整理候选证据，不调用 Qwen，可由 Codex 中的 Skill 继续处理。

## 从源码复现

测试环境：Windows x64、Python 3.12.7、Node 22.22.0。新环境先确认 python 为 3.12，再执行 python -m venv .venv 创建虚拟环境；已有环境跳过创建。然后运行：

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r ".\requirements.lock.txt"
& ".\.venv\Scripts\python.exe" -X utf8 ".\scripts\download_demo.py"
& ".\.venv\Scripts\hf.exe" download intfloat/multilingual-e5-small --revision 614241f622f53c4eeff9890bdc4f31cfecc418b3 --cache-dir ".\models\hf_cache" --include config.json modules.json sentence_bert_config.json special_tokens_map.json tokenizer.json tokenizer_config.json "1_Pooling/config.json" model.safetensors sentencepiece.bpe.model README.md
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research build
& npm.cmd --prefix ".\frontend" ci --no-audit --no-fund
& npm.cmd --prefix ".\frontend" run build
```

上述命令从来源网站下载论文和模型缓存，再建立索引。论文文件与索引按需生成，版本见 [语料清单](data/corpus_manifest.json)。

## 验证与实验

```powershell
& ".\.venv\Scripts\python.exe" -X utf8 ".\scripts\verify_project.py"
& ".\.venv\Scripts\python.exe" -X utf8 ".\scripts\create_demo_cases.py"
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research evaluate
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research tune
& ".\.venv\Scripts\python.exe" -X utf8 ".\scripts\run_live_smoke.py"
& ".\.venv\Scripts\python.exe" -X utf8 -m paper_research gepa --budget 12 --output ".\output\gepa_run"
```

live_smoke 与 GEPA 会调用已配置的模型。重型本地模型任务请顺序运行。评测集只有 18 个手工问题，不能把它当作官方 QASPER benchmark。GEPA 只产生候选策略，默认不替换已使用的提示词。

## 在 Codex 中使用 Skill

以本项目文件夹作为工作目录，使用 `paper-research` 技能。技能入口是 [.agents/skills/paper-research/SKILL.md](.agents/skills/paper-research/SKILL.md)。
从父目录打开聊天时，不应假定它会自动发现子目录技能；可显式指定技能文件路径。

## 范围

本版本处理已导入的论文，支持摘要/全文范围、混合检索、引用回填、有限重试、报告下载和实验记录。没有实现公开互联网自主搜索、OCR、跨编码器 reranker、分布式任务队列或生产级用户权限，详见交付报告。
