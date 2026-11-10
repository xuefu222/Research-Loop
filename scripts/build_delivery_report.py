"""生成含真实指标、逐文件说明和面试问答的中文交付报告。"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_research.config import read_json

DESCRIPTIONS = {
".gitignore":"忽略虚拟环境、模型缓存、本地密钥、数据库和构建目录。",
"pyproject.toml":"项目元数据、Python 依赖声明、命令行入口与 pytest 配置；当前主要从源码目录运行。",
"requirements.txt":"基础 PDF/Embedding 依赖与 CPU PyTorch 来源，并引入应用依赖清单。",
"requirements-app.txt":"LangGraph、FastAPI、混合检索、上传、GEPA 和测试工具的直接依赖。",
"requirements.lock.txt":"本机实际安装的完整版本清单；含 Windows/Python 3.12 对应 CPU PyTorch 链接。",
"README.md":"快速启动、从源码复现、实验命令与能力边界。",
"config/model.example.json":"可复制的模型配置示例，不含真实密钥。",
"config/model.local.json":"实际 Qwen 接口与密钥，只在本地保存且被 Git 忽略；报告不展示其内容。",
"config/retrieval.json":"实际使用的候选数、最终数量、RRF 常数、权重、去重、上下文和轮次预算。",
"paper_research/__init__.py":"包入口与版本号。",
"paper_research/__main__.py":"统一 CLI：build/search/research/serve/evaluate/tune/gepa。",
"paper_research/config.py":"项目路径、配置读取与 JSON 原子写入。",
"paper_research/legacy.py":"按需导入前面课程中的独立脚本，复用已实现的提取、清洗与校验逻辑。",
"paper_research/embedding.py":"共享本地 E5 模型、线程锁、512-token 检查、归一化和查询缓存。",
"paper_research/indexing.py":"PDF 入库、摘要边界识别、超长切分、增量向量复用与索引原子替换。",
"paper_research/retrieval.py":"BM25、向量检索、加权 RRF、材料范围过滤与重叠去重。",
"paper_research/model.py":"Qwen 兼容 HTTP 调用，限制调用次数，瞬断最多重试一次，并记录无密钥的调用审计。",
"paper_research/grounding.py":"从原文构造 U 证据单元，校验证据编号和引用，回填原文与实际页码/字符位置。",
"paper_research/workflow.py":"LangGraph 状态、节点、审核分支、有限补检索、失败保守返回及轨迹。",
"paper_research/reporting.py":"保存证据包、草稿、最终 JSON、Markdown、用量和节点轨迹。",
"paper_research/storage.py":"SQLite 任务和事件存储，WAL，显式关闭连接，重启时标记未完成任务。",
"paper_research/api.py":"网页/API、后台线程池、文件上传、任务查询、SSE 和报告下载。",
"paper_research/evaluation.py":"原页区间金标准、Hit/证据召回/MRR、时延评测和仅用训练/验证的权重比较。",
"paper_research/optimization.py":"真实 GEPA 适配器：选择提示词评测、失败反馈、反思优化、保留测试与候选保存。",
"prompts/plan.txt":"把原始问题转换为语义检索问句与英文关键词，不填入猜测答案。",
"prompts/select.txt":"选择可支持回答的候选片段，输出短编号。",
"prompts/answer.txt":"根据 U 单元形成回答；引用由程序回填，禁止外部记忆补答。",
"prompts/review.txt":"按实际主张审核证据语义支持，避免仅因同义转述而否定。",
"scripts/download_demo.py":"下载固定版本开放论文，保留 PDF、来源、校验和与许可链接。",
"scripts/create_demo_cases.py":"把人工核对的论文段落定位为原页字符区间，生成 18 个示例问题。",
"scripts/search_compat.py":"供 Skill 独立检索脚本调用的兼容命令行入口。",
"scripts/run_live_smoke.py":"付费接口小规模验收：摘要数量/GPU、直接事实比较、无关问题拒答。",
"scripts/verify_project.py":"默认不调用生成模型，检查源代码、索引、原文对应、密钥、依赖及全部测试。",
"scripts/build_delivery_report.py":"读取真实实验结果和文件清单，生成本报告。",
"frontend/package.json":"Vue/Vite 固定版本与启动/构建命令。",
"frontend/package-lock.json":"前端完整依赖锁，供 npm ci 复现。",
"frontend/index.html":"开发页面 HTML 入口。",
"frontend/vite.config.js":"本地开发 API 代理和 web 构建输出目录。",
"frontend/src/main.js":"Vue 页面：论文选择、范围、上传、问题提交、SSE、报告和下载。",
"frontend/src/style.css":"本地工作台样式；不依赖在线字体。",
".agents/skills/paper-research/SKILL.md":"Skill 入口：触发范围、证据约束、宿主/独立模式与真实校验要求。",
".agents/skills/paper-research/references/output_format.md":"五字段正式 JSON 报告规范；不是模型内部草稿规范。",
".agents/skills/paper-research/references/local_workflow.md":"本地检索、packet、U 引用、独立 Agent 的具体工具使用方式。",
".agents/skills/paper-research/scripts/validate_report.py":"原有结构与引用编号检查；不判断答案语义正确性。",
".agents/skills/paper-research/scripts/read_pdf.py":"原有逐页 PDF 文字提取，记录校验和与解析器版本。",
".agents/skills/paper-research/scripts/chunk_text.py":"原有字符切分工具，保留 raw_text、清洗文本及原页位置。",
".agents/skills/paper-research/scripts/build_embeddings.py":"课程阶段单篇论文向量生成工具；最初的 68 条结果保留。",
".agents/skills/paper-research/scripts/search_keywords.py":"课程阶段关键词覆盖率检索基线；它不是 BM25。",
".agents/skills/paper-research/scripts/search_embeddings.py":"独立纯向量检索兼容入口，可读最初单篇索引。",
".agents/skills/paper-research/scripts/search_hybrid.py":"独立 BM25 + E5 + RRF 检索入口。",
".agents/skills/paper-research/scripts/assemble_report.py":"把宿主生成的 U 编号草稿变为有真实原文与位置的正式报告。",
"tests/conftest.py":"隔离的合成小索引与假 Embedding；不会把单测分数当真实检索效果。",
"tests/test_retrieval.py":"RRF、零权重、范围前置、单文档 BM25、空结果、去重与输出字段。",
"tests/test_grounding.py":"真实引文位置、虚构引用、不存在片段、漏题和冲突证据约束。",
"tests/test_workflow.py":"工作流角色、有限重试、审核拒绝、packet 与提供方错误。",
"tests/test_units.py":"U 单元回填、未知单元、跨文献来源覆盖和网络重试预算。",
"tests/test_api.py":"HTTP 状态、SSE 重放、上传去重、重启状态与数据库连接关闭。",
"evals/cases.json":"18 个自建问题；16 条有原页证据，2 条用于拒答测试，非官方 QASPER 测试集。",
"data/corpus_manifest.json":"四篇演示论文的稳定编号、题目、版本、来源与论文级划分。",
"data/index/corpus.json":"当前多论文索引，含模型版本、来源、区间、摘要标签、向量和指纹。",
"data/app.sqlite3":"本地任务、请求、结果和事件数据库；不保存模型密钥。",
"output/acceptance.json":"最后一次本地验收结果及真实测试/依赖检查输出。",
"output/api_smoke.json":"真实 HTTP、后台任务、下载、SSE 和重放验收。",
"output/frontend_smoke.json":"Vue 开发服务器到后端的真实 API 代理检查，及页面截图位置。",
"output/live_smoke_results.json":"真实模型三个演示任务的局部断言结果，不代表通用准确率。",
"output/retrieval_evaluation.json":"三种检索方式的逐题结果、分组指标、时延、版本和限制。",
"output/retrieval_tuning.json":"只用训练/验证比较权重的记录；未自动替换默认策略。",
"output/model_calls.jsonl":"模型调用审计：角色、时间、状态、模型与 usage，不记录请求头和密钥；model=test 为合成测试事件。",
"output/ui-dashboard.png":"已实际渲染并人工检查的本地网页截图。",
"output/qasper_embeddings.json":"最初单篇课程索引：68 个 384 维向量，和现在的 355 条多论文索引分开保留。",
"output/qasper_chunks.json":"最初单篇课程的 68 个字符片段。",
"output/qasper_pages.json":"最初 QASPER 的 12 页文字提取结果。",
"output/qasper_search.json":"最初关键词覆盖率检索结果，不是最终混合检索。",
"output/qasper_report.json":"早期摘要问答的结构化示例。",
"output/qasper_report_checked.json":"早期实际运行结构校验通过的摘要示例。",
"output/qasper_report.invalid_reference.json":"故意使用不存在的引用编号的负例。",
"output/validation_results.json":"早期结构校验正负例的真实退出码与结果。",
"output/qasper_report_checked.validation.json":"早期报告校验与技能结构校验记录。",
"output/pdf_extraction_verification.json":"PDF 文字提取和页面 1/7 的人工抽查记录，包括表格/公式局限。",
"output/embedding_verification.json":"最初 68 条向量的来源、数值、位置与环境验证。",
"output/embedding_build.log":"最初单篇向量生成的日志。",
}

FAQ = [
("怎样用半分钟介绍项目？",
 "这是面向论文阅读的证据研究助手。用户选论文与材料范围后，系统用 BM25 和多语言向量混合召回，经过证据选择、回答与审核生成可回查原文的报告。重点是范围控制、引用溯源、有限重试和可复现实验；当前是本地研究工具。",
 "workflow.py、retrieval.py、grounding.py", ""),
("这到底是 Agent，还是普通工作流？",
 "它是工作流式 Agent：主要阶段由 LangGraph 固定，模型负责检索问句、材料选择和回答，审核结果决定是否补查。没有让模型自由执行任意工具，也没有实现跨组织多 Agent 协作。把它说成通用自主 Agent 会超出实现。",
 "State、research、route", "https://docs.langchain.com/oss/python/langgraph/graph-api"),
("Skill、Tool、MCP、A2A 分别负责什么？",
 "Skill 提供任务方法和资源；Tool 执行具体操作。MCP 主要标准化 AI 应用与外部工具/数据的连接，A2A 面向 Agent 间互操作。本项目有 Skill 和 Python 工具，没有实现 MCP server 或 A2A 协议，图里的箭头不能叫 A2A。",
 "SKILL.md、scripts/", "https://developers.openai.com/plugins/concepts/skills | https://modelcontextprotocol.io/docs/getting-started/intro | https://a2a-protocol.org/latest/topics/what-is-a2a/"),
("为什么用 LangGraph？为什么没有再套 Deep Agents？",
 "项目有共享状态、审核分支和有限循环，显式图有利于检查终止条件和保留轨迹。当前节点很明确，普通 Python 也能实现；LangGraph 是控制流选择。Deep Agents 的规划/子 Agent/上下文能力在这里不是必要依赖，因此没有叠加。",
 "workflow.py；图的节点与条件边", "https://docs.langchain.com/oss/python/langgraph/overview | https://docs.langchain.com/oss/python/deepagents/overview"),
("主 Agent 与审核 Agent 是否独立？",
 "它们是不同提示词和职责的调用，按你的要求使用同一 qwen-max 服务。主流程产出答案，审核角色判断语义支持。相同模型会有相关错误，不能当作独立验证；程序负责引用真实性，困难事实仍需人工复核。",
 "prompts/answer.txt、prompts/review.txt、model.py", ""),
("RAG 与 LoRA 有什么关系？",
 "RAG 在推理时提供检索材料，便于更新知识和保留出处；LoRA 通过低秩增量适配模型行为，改变参数。两者可组合，但本项目没有训练 Qwen 或 E5。这里的论文是检索语料，18 个问题是评测样本，不是 LoRA 训练集。",
 "data/raw、evals/cases.json、embedding.py", "https://arxiv.org/abs/2005.11401"),
("一条请求经过哪些步骤？",
 "输入问题与范围→规划检索问句→过滤允许论文/章节→双路检索与 RRF→去重和上下文预算→选候选→构造 U 单元→生成答案→程序回填/检查→模型审核。失败时最多补查到两轮，仍失败就保守返回不足。",
 "workflow.py 的 plan/retrieve/select/draft/verify/finish", ""),
("BM25 的核心是什么？你用哪个版本？",
 "结合逆文档频率、词频饱和与长度归一化。本项目用 rank-bm25 的 Okapi 词频/长度计算，k1 默认 1.5、b 默认 0.75；IDF 改为正的 log(1+(N-df+0.5)/(df+0.5))，避免极小过滤语料中命中项全为负。不是完整复刻 Lucene 的全部打分实现。",
 "retrieval.py 的 BM25Okapi 与 idf 赋值", "https://github.com/apache/lucene/blob/main/lucene/core/src/java/org/apache/lucene/search/similarities/BM25Similarity.java"),
("Embedding 模型为什么这样用？",
 "当前固定 multilingual-e5-small 的模型提交，输出 384 维，输入上限 512 tokens。论文用 passage: 前缀，问题用 query: 前缀；两侧归一化后用点积计算余弦相似度。更换模型时应重新建库，不能仅因维度相同就混用。",
 "embedding.py、config.py、indexing.py", "https://huggingface.co/intfloat/multilingual-e5-small"),
("为什么混合检索？",
 "词法检索善于名称、缩写和精确术语，向量检索善于语义近似和跨语言表达。两者可能互补，但不是必然提升。本项目保留分支排名与分数，允许通过同一问题集检查收益和退化。",
 "Retriever.search；BM25/dense/hybrid 三种模式", ""),
("RRF 的公式和优势是什么？",
 "本项目分数为 alpha/(60+rank_dense)+(1-alpha)/(60+rank_bm25)，不在某分支出现的项贡献 0。它融合排名，避免直接相加不同尺度的原始分数。60 是平滑常数，绝非通用最优值；融合后仍要评测。",
 "fuse_rankings；config/retrieval.json", "https://lintool.github.io/robust04-analysis-papers/p758-cormack.pdf"),
("top_k、candidate_k、rrf_k 是一回事吗？",
 "不是。top_k 当前为 6，是单次检索最终候选数；candidate_k 为 24，是各分支参与融合的池大小；rrf_k 为 60，是排名平滑常数。评测固定看前 5 条。补查轮次会扩大候选，不能把这些数字混称一个 k。",
 "config/retrieval.json、Retriever.search、evaluation.py", ""),
("中文问题如何匹配英文论文？",
 "稠密分支直接使用多语言模型。在线 Agent 规划器生成英文检索问句与稀疏关键词；纯检索 CLI 只有显式术语扩展，也支持手工 lexical_query。词典不是完整翻译器。离线集给定英文词，因此不能用该分数证明在线翻译质量。",
 "ALIASES、expand_query、prompts/plan.txt", ""),
("为什么切分 PDF？字符长度和 token 长度有什么区别？",
 "实际切分的是提取文字，原始 PDF 不改。先按 1000 字符、重叠 200 做窗口，保留原页位置；编码前再检查 token。本次新论文出现 644-token 窗口，程序通过有重叠的递归细分处理，没有静默截断。字符位置是 Python 字符索引，不是 UTF-8 字节位置。",
 "chunk_text.py、fit_chunks、Embedder.encode", ""),
("为什么重叠？如何去重？",
 "重叠降低边界上下文被切断的概率，不保证句子或公式完整。检索后只在同文档同页比较区间，交集除以较短片段长度达到 0.65 时去重。不同论文的相同事实保留，便于比较；去重也可能影响召回，需要回归检查。",
 "overlapping、Retriever.search", ""),
("仅摘要范围怎样避免泄漏正文？",
 "入库时单独划出有明确边界的摘要区域，切分不跨边界；检索先筛文档与 section=abstract，再计算分支排名。没有可信边界就不给全文兜底。网页摘要任务由 Skill 限制宿主读取。自动标题识别仍有版式局限，不能声称适用于所有 PDF。",
 "abstract_range、document_chunks、Retriever.search", ""),
("如何证明引文不是模型编造的？",
 "程序先从 raw_text 构建 U 单元，模型只返回短编号。后端用编号取出原文，在候选原文中找连续子串，再从原页起点计算位置；来源和 PDF 页码由数据决定。这样能检查出处与文本一致，不能自动证明语义蕴含。",
 "evidence_units、canonicalize、assemble_report.py", ""),
("JSON 合法为什么还不够？",
 "能解析不等于字段类型、引用编号、问题覆盖和语义都正确。试跑中出现 citations=null 或错误嵌套，校验器拒绝了这些结果。后来把长编号/原文复制改成短 U 引用，由程序回填。结构检查和模型语义审核分别负责不同问题。",
 "grounding.py、validate_report.py、output/demo_qasper_v2", ""),
("没答案时能靠相似度阈值拒答吗？",
 "不能直接拿统一阈值当正确率。向量检索总能给出最相近项，E5 的绝对分数也不等于支持概率。本项目查看实际材料，允许证据选择为空、答案不足或审核失败；无关问题能拒答，但尚未在大规模无答案集上校准。",
 "select、draft、insufficient_report", "https://huggingface.co/intfloat/multilingual-e5-small#faq"),
("跨论文比较如何防止只引用一篇？",
 "针对明确的比较任务，补充各篇候选，并检查有结论的回答是否覆盖每篇指定来源；不能只依赖一篇对另一篇的转述。这里检查的是来源覆盖，语义比较仍由审核与人工承担。选择论文时只勾选实际要比较的文献。",
 "required_sources、canonicalize、live_comparison", ""),
("你做 rerank 了吗？",
 "没有部署训练过的 Cross-Encoder reranker。RRF 是排名融合，后面另有一次 LLM 证据选择，二者不能混称 Cross-Encoder。若召回池有正确材料但最终选错，可以加重排再测质量与时延，不能只添加技术名。",
 "retrieval.py 与 select 节点", ""),
("为什么没有 Chroma、FAISS 或 HNSW？",
 "当前只有 355 个 384 维向量，float32 矩阵约 0.52 MiB，精确 NumPy 扫描足够透明。主要资源成本在模型加载而非矩阵。规模扩大时再比较 ANN 的召回、内存和延迟；本版本没有实现向量数据库，不在简历写已使用。",
 "Retriever.vectors；scores 的矩阵点积", "https://github.com/facebookresearch/faiss/wiki/Faiss-indexes"),
("文档更新如何处理？",
 "来源有完整文件 SHA-256；片段编号绑定 PDF 校验和、页码与字符区间。同模型版本且片段文本不变时复用向量。索引临时写完后原子替换；上传同一 PDF 复用文档，入库失败不把临时清单提交为正式清单。更换解析/清洗规则也应检查并重建。",
 "build_index、write_json、ingest_job、upload_document", ""),
("为什么不直接把全文丢给长上下文模型？",
 "短论文可以全文输入，这应作为待比较的基线。多论文时检索能控制材料量、调用成本与证据定位，但可能漏证据。长上下文也不保证均匀利用各个位置的信息。本项目尚未做严格的全文输入对照，不能宣称检索一定更准确。",
 "上下文预算 max_context_chars=18000", "https://arxiv.org/abs/2307.03172"),
("Hit@5、证据召回率、MRR@5 怎么算？",
 "Hit 看前 5 是否命中任一标注证据；证据召回看所需证据组覆盖比例；MRR 是首个正确项排名倒数，未命中为 0。这里用原页区间作为金标准，避免重叠窗口被当作不同正确事实。16 条正例目前各只有一组证据，所以 Hit 与召回数值相同。",
 "covers、metrics、evals/cases.json", ""),
("评测集从哪里来？怎样避免泄漏？",
 "18 个问题由本次项目手工设计并核对原文，16 个有证据，2 个做拒答检查。QASPER/RAG 是训练论文，Attention 是验证，Self-RAG 是保留测试。GEPA 只向反思器提供训练轨迹，验证选候选，优化结束后再测保留论文；极小规模仍不足以证明泛化。",
 "create_demo_cases.py、validate_cases、optimize_selection", ""),
("你实际证明混合检索最好了吗？",
 "没有。当前 16 条正例上 BM25 命中 16/16，纯向量 11/16，混合 14/16。英文关键词由人工给定，语料与问题都少，条件偏向词法分支。可以说混合在该集合比纯向量多命中 3 条，不能说业务准确率提升或超过所有方法。",
 "output/retrieval_evaluation.json", ""),
("如何测延迟？缓存会不会让比较失真？",
 "本次先预热模型，再对 dense/hybrid 的每条查询清空向量缓存，使用高精度 perf_counter。时间含分支检索与排序，不含每次重载权重；冷启动单列。没有做并发压测，P95 仅来自 16 个点，不能作为服务 SLA。",
 "evaluation.py 的 timing_policy、latency_p95_ms", ""),
("GEPA 在这个项目优化了什么？",
 "优化 prompts/select.txt 对应的证据选择提示词，不改 Qwen 权重或检索模型。适配器用原文证据区间计算选择召回/精度，并把失败轨迹反馈给反思模型，产生候选后在验证论文上比较。它是离线实验入口，不是自动改线上行为。",
 "SelectionAdapter、optimize_selection", "https://arxiv.org/abs/2507.19457"),
("GEPA 的实际结果是什么，为什么不自动上线？",
 "引擎最终记录 12 次样本评测、2 个保留候选（含基线），验证均分相同为 0.975；最佳仍是基线，保留测试二者都是 1.0。样本只有训练/验证/测试各两条，不能据此说进化有效。生成候选还出现过记住训练编号的倾向，所以保持不自动发布。",
 "output/gepa_final/result.json、candidates.json、engine", ""),
("Self-RAG、自我审核与自进化有什么区别？",
 "Self-RAG 论文训练模型使用特殊反思 token。这里的审核是一次任务内的质量检查；GEPA 是跨样本优化提示词的离线循环。项目没有训练出 Self-RAG 模型，也没有实现持续无人值守、自主发布新策略的系统。",
 "prompts/review.txt 与 optimization.py", "https://arxiv.org/abs/2310.11511v1"),
("怎样避免 Agent 无限循环或费用失控？",
 "最多 5 个问题、两轮检索/生成、8 次 HTTP 调用，输出 token 和请求超时有上限；瞬断至多重试一次且计入调用预算。GEPA 另外限制样本评测、反思次数、实际请求与时间。当前没有全局多租户配额，usage 也不是账单。",
 "model.py、workflow.py、optimization.py、config", ""),
("模型接口失败会被当成论文没答案吗？",
 "不会。网络或鉴权等基础设施错误让任务失败，展示可诊断状态；格式/证据审核两轮失败才保守返回不足并保留原因。远程瞬断和 HTTP 400 是不同问题：前者有限重试，后者检查输入协议或配置，不盲目重试。",
 "ModelClient.text、queue_research、trace.json", ""),
("FastAPI 的 async 能自动加速模型计算吗？",
 "不能。异步适合等待 I/O，CPU 推理仍需要资源。本项目后台线程池处理任务，同进程共享一个 Embedding 实例并用锁串行编码；SSE 用 async 等待。真正高负载时应拆推理服务与任务队列，不能靠改成 async def 就声称并行推理。",
 "api.py、embedding.py", "https://fastapi.tiangolo.com/async/"),
("为什么用 SSE，而不是 WebSocket？",
 "这里主要是服务端向浏览器推送阶段进度，单向 SSE 已够用；事件有递增 ID，浏览器断线后带 Last-Event-ID 重放 SQLite 中之后的事件。当前是阶段事件流，不是逐 token 流。双向实时交互才更需要考虑 WebSocket。",
 "events、Store.events、frontend EventSource", "https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events"),
("SQLite 持久化是否等于 LangGraph 断点恢复？",
 "不是。SQLite 保存任务状态、事件和结果，重启后未完成任务标为 interrupted，需要重新提交。没有给业务图配置持久 checkpointer，所以不能从任意节点自动继续。GEPA 自身的实验断点是另一条链路，不应混淆。",
 "Store.recover、workflow graph.compile()", "https://docs.langchain.com/oss/python/langgraph/persistence | https://www.sqlite.org/wal.html"),
("如何处理论文里的提示注入？",
 "论文文本被声明为数据，模型只可返回查询/编号/回答；程序不执行论文里的命令，不允许它指定文件位置或源 URI。编号、范围和引文由代码约束，页面也不通过 v-html 执行模型输出。这些措施降低风险，不构成已证明的全面防护。",
 "prompts、canonicalize、Vue 模板", "https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html"),
("密钥、上传文件和 SQL 怎么保护？",
 "密钥在 Git 忽略的本地配置或环境变量，只由后端发出，健康接口不返回。上传用内容哈希生成路径、限制大小、验证 PDF 并去重；SQL 用参数绑定。当前只提供本机演示，没有用户认证、文档 ACL 或多租户隔离，不能直接称生产服务。",
 "model.local.json、upload_document、Store", ""),
("你有哪些真正运行过的测试？发现了什么？",
 "包括合成行为测试、真实索引与原页对应、真实 Qwen 冒烟、HTTP/SSE/下载和页面渲染。发现过公式 token 溢出、嵌套 JSON 引用错误、比较只引用一篇、网络瞬断和并行权重加载资源不足。单测用假模型隔离控制流，真实调用单独记录，不能混用为准确率。",
 "output/acceptance.json、api_smoke.json、live_smoke_results.json", ""),
("项目的主要不足与下一步是什么？",
 "只有 4 篇论文和小型手工集；复杂检索/比较可能保守拒答；同模型审核有偏差；PDF 表格公式与 OCR 未解决；没有分布式队列和业务鉴权。优先扩充按论文分离的人工证据集、重复测稳定性、做全文输入与 reranker 对照，再决定是否扩展框架。",
 "output/regressions/comparison_timing、评测限制", ""),
("如果问到 Attention 公式，与项目有什么联系？",
 "缩放点积注意力为 softmax(QK^T/sqrt(dk))V，缩放用于控制点积随维度增长的尺度。E5 是用于表示文本的编码模型，Qwen 用于生成；本项目调用预训练模型，没有重写 Attention 或训练其权重。不要把调用模型说成实现了模型结构。",
 "Embedding 与生成模型职责划分", "https://arxiv.org/abs/1706.03762v7"),
("现场实现 RRF / Top-k / MRR 怎么回答？",
 "RRF 用字典累计每个编号在各路的 weight/(k+rank)，再排序取前 k；p 个候选全排序 O(p log p)，只取少量可用堆做到 O(p log k)。MRR 扫描结果直到首个覆盖金标准的项，返回 1/rank，无命中返回 0。要测试空列表、重复编号、零权重和多证据。",
 "fuse_rankings、metrics、tests/test_retrieval.py", ""),
]

def purpose(relative):
    if relative in DESCRIPTIONS:
        return DESCRIPTIONS[relative]
    path=Path(relative)
    if relative.startswith("data/raw/"):
        return "原始论文 PDF（未修改）" if path.suffix==".pdf" else "对应原始论文的来源、版本、SHA-256、获取记录和许可链接；保留前期来源记录。"
    if relative.startswith("data/processed/"):
        return "对应论文逐页提取结果，供字符区间、摘要边界和金标准回查。"
    if relative.startswith("output/regressions/"):
        return "保留的困难比较回归样本；审核未通过时的证据、草稿、报告或轨迹，不作为成功演示。"
    if relative.startswith(("output/demo_qasper/", "output/demo_qasper_v2/", "output/gepa_demo/")):
        return "开发诊断与失败尝试记录；可用于理解结构或接口问题，不是最终验收产物。"
    if "/gepa_final/" in relative:
        return {"result.json":"最终 GEPA 指标、划分、候选选择、保留测试和未发布标记。",
          "candidates.json":"引擎保留的全部候选、父子关系与验证分数。",
          "candidate_prompt.txt":"最佳候选文本；本次等同保留的基线，未自动替换线上提示词。"}.get(path.name,
            "GEPA 引擎的断点、日志或内部轨迹，用于恢复与审计；不是模型权重。")
    if relative.startswith("output/verification/"):
        return "前期 PDF 第 1/7 页的渲染图片，用于人工核对提取质量。"
    if relative.startswith("output/"):
        if path.name=="report.json": return "正式结构化报告，含回答状态、原文证据、来源和限制。"
        if path.name=="report.md": return "同一报告的中文可读 Markdown。"
        if path.name=="evidence_packet.json": return "本任务实际取得的候选、材料范围、来源和 U 证据单元。"
        if path.name=="drafts.json": return "模型返回的中间草稿，失败或通过均不应越过最终校验直接使用。"
        if path.name=="trace.json": return "节点、耗时、分支与重试事件。"
        if path.name=="run.json": return "任务模式、轮次、提示词哈希、请求用量与核验状态。"
        if path.suffix in (".bin",".pkl"): return "实验引擎内部断点数据。"
        return "本地运行或实验产物；结合其父目录区分课程阶段、诊断、最终演示或验收。"
    if relative.startswith("data/app.sqlite3"):
        return "SQLite 的 WAL/共享内存配套文件，属于任务数据库运行状态。"
    return "项目辅助文件；其具体调用方与用途可从同目录代码或本文架构定位。"

def inventory():
    paths=[]
    for directory,folders,filenames in os.walk(ROOT):
        folders[:]=[name for name in folders if name not in (".venv","node_modules","models","web",".git","__pycache__",".pytest_cache")]
        for name in filenames:
            path=Path(directory)/name
            relative=path.relative_to(ROOT).as_posix()
            if relative.startswith("docs/"):
                continue
            paths.append(relative)
    code_paths=[p for p in sorted(paths) if not p.startswith(("data/","output/","evals/"))]
    data_paths=[p for p in sorted(paths) if p not in code_paths]
    return code_paths,data_paths

def table(paths):
    return "\n".join("| ["+path+"](../"+path+") | "+purpose(path).replace("|","／")+" |" for path in paths)

def main():
    index=read_json(ROOT/"data/index/corpus.json")
    evaluation=read_json(ROOT/"output/retrieval_evaluation.json")
    acceptance=read_json(ROOT/"output/acceptance.json")
    live=read_json(ROOT/"output/live_smoke_results.json")
    gepa=read_json(ROOT/"output/gepa_final/result.json")
    api_path=ROOT/"output/api_smoke.json"
    api=read_json(api_path) if api_path.exists() else {}
    test_output=acceptance["commands"]["tests"]["stdout"]
    count=re.search(r"(\d+) passed",test_output)
    tests=count.group(1) if count else "见原始记录"
    date=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    source_rows="\n".join(f"| {source['doc_id']} | {source['title']} | {source['page_count']} | {sum(row['doc_id']==source['doc_id'] for row in index['chunks'])} | {source.get('version','')} |"
        for source in index["sources"])
    metric_rows="\n".join(f"| {row['method']} | {row['n']} | {row['hit_at_5']:.2%} | {row['evidence_recall_at_5']:.2%} | {row['mrr_at_5']:.4f} | {row['latency_p50_ms']:.2f} | {row['latency_p95_ms']:.2f} |"
        for row in evaluation["summary"] if row["split"]=="all")
    live_rows="\n".join(f"| {row['case_id']} | {', '.join(row['statuses'])} | {row['model_calls']} | {row['tokens']} | {'通过' if row['passed'] else '未通过'} |"
        for row in live["cases"])
    code_paths,data_paths=inventory()
    text=f"""# Paper Research：项目交付与面试准备报告

生成日期：{date}（Asia/Shanghai）  
资料检索日期：2026-11-07  
项目目录：D:/lora/paper-research-skill  
版本：0.2.0

## 阅读顺序

先看“能做什么”和“运行方式”，然后按 workflow → retrieval → grounding → api → tests 阅读代码。
后面给出逐文件说明、真实测试、{len(FAQ)} 个问题及答案、简历表述和复习顺序。

## 1. 项目已经完成什么

这是一套基于已导入论文的调研与证据核验工具，可以作为 Codex Skill 使用，也可以独立运行 Qwen Agent。
当前有 Vue 3 工作台、FastAPI 接口、LangGraph 有限流程、混合检索、证据回填、审核、报告下载、实验与测试。

| 层 | 实际实现 |
|---|---|
| 技能 | paper-research；本地与网页材料分别处理，遵守摘要/全文限制 |
| 数据 | 原始 PDF、来源清单、逐页文字、原页字符位置、论文级划分 |
| 检索 | 正 IDF BM25 + multilingual-e5-small，精确向量计算与加权 RRF |
| 控制流 | 规划 → 检索 → 选择 → 回答/引用检查 → 审核 → 完成或有限补查 |
| 模型 | 主流程与审核均使用你提供的 qwen-max 兼容接口；不是两个独立模型 |
| 接口 | 上传、后台任务、状态查询、SSE、JSON/Markdown 下载 |
| 网页 | Vue 3 + Vite，页面与 API 同源提供 |
| 存储 | SQLite 任务/事件，JSON 文件记录数据与实验 |
| 优化 | GEPA 证据选择提示词实验；候选不自动替换默认提示词 |

没有实现通用互联网自主研究、OCR、训练版 Self-RAG、Cross-Encoder reranker、Chroma、A2A 或多租户生产平台。
这些不应写成已完成能力。Deep Agents 没有作为额外运行框架接入；模型调用使用 HTTPX，LangGraph 的依赖不等于应用采用了全部 LangChain 组件。

### 结构图

```mermaid
flowchart TD
  U[用户选论文与范围] --> A[FastAPI / Skill / CLI]
  A --> P[LangGraph 规划]
  P --> R[范围前置过滤]
  R --> B[BM25]
  R --> D[E5 向量检索]
  B --> F[加权 RRF 与去重]
  D --> F
  F --> S[模型选择候选]
  S --> E[程序生成 U 证据单元]
  E --> G[模型回答]
  G --> C[程序回填原文与位置]
  C --> V[模型语义审核]
  V -->|通过| O[保存报告与轨迹]
  V -->|未通过且未到两轮| R
  V -->|达到上限| N[保守返回不足并保留原因]
```

## 2. 直接使用和独立复现

当前环境和模型缓存已准备好。PowerShell：

```powershell
Set-Location "D:\\lora\\paper-research-skill"
& ".\\.venv\\Scripts\\python.exe" -X utf8 -m paper_research serve --port 8765
```

打开 [本地工作台](http://127.0.0.1:8765) 或 [API 文档](http://127.0.0.1:8765/docs)。
如果本次交付启动的服务仍在运行，直接打开即可。

建议演示顺序：

1. “摘要边界测试”：数量回答 supported，GPU 问题 insufficient。
2. “跨论文比较”：选择 RAG 和 Self-RAG，核对两篇直接证据。
3. 在 QASPER 中问无关的蛋糕问题：应保守返回不足。
4. 下载报告，查看 report.json、evidence_packet.json、trace.json 和 run.json。
5. 上传已存在的 PDF，观察重复内容被复用，不破坏索引。

从新环境完整重建的命令见 [README](../README.md)。先准备 Python 3.12 虚拟环境，安装锁定依赖和模型缓存，再下载论文、建库和构建前端。
保留的 requirements.lock.txt 对应 Windows x64/Python 3.12；远程 qwen-max 是提供方别名，温度为 0 也不保证每次文本完全相同。
本次是在当前独立环境实际运行，没有清空并重新安装整个环境；锁文件是实际安装快照。

命令行常用入口：

```powershell
& ".\\.venv\\Scripts\\python.exe" -X utf8 -m paper_research search --query "QASPER 有多少问题？" --doc-id qasper --scope abstract --method hybrid
& ".\\.venv\\Scripts\\python.exe" -X utf8 -m paper_research research --question "QASPER 有多少问题？" --doc-id qasper --scope abstract
& ".\\.venv\\Scripts\\python.exe" -X utf8 -m paper_research research --question "QASPER 有多少问题？" --doc-id qasper --scope abstract --mode packet
& ".\\.venv\\Scripts\\python.exe" -X utf8 ".\\scripts\\verify_project.py"
```

packet 模式不调用生成接口，宿主可继续使用 U 单元组装报告。独立 agent、live_smoke 和 GEPA 会调用已配置的模型。
本机出现过多个 Python 进程同时加载权重导致 Windows 页面文件资源不足；重型模型实验顺序运行，服务进程内共享模型，不修改系统分页设置。

## 3. 每个文件代表什么

### 3.1 自有源码、配置、技能、前端与测试

| 文件 | 作用 |
|---|---|
{table(code_paths)}

### 3.2 原始资料、中间结果与实验产物

下面保留了课程阶段、失败诊断和最终结果。日常演示优先使用 live_*、api_smoke、acceptance 和 gepa_final。

| 文件 | 作用 |
|---|---|
{table(data_paths)}

### 3.3 第三方环境与自动生成目录

| 目录/文件 | 含义 |
|---|---|
| .venv/ | 第三方 Python 环境；不逐项当作业务文件讲解，版本由锁文件记录 |
| frontend/node_modules/ | Vue/Vite 等前端依赖；由 npm ci 恢复 |
| frontend/package-lock.json | 前端依赖版本与下载完整性信息 |
| web/index.html | Vite 编译后的页面入口，由 FastAPI 提供 |
| web/assets/*.js、*.css | 构建后的代码与样式；应修改 frontend/src 再构建 |
| models/hf_cache/.../model.safetensors | 已下载 E5 权重，不是本项目训练出的模型 |
| 模型缓存中的 tokenizer.json、sentencepiece.bpe.model | 把文本转成 token 的分词器资料 |
| 模型缓存中的 config.json、modules.json、sentence_bert_config.json | 网络、模块顺序和编码配置 |
| 模型缓存中的 1_Pooling/config.json | 池化配置，用于得到文本向量 |
| 模型缓存中的 special_tokens_map.json、tokenizer_config.json | 特殊 token 与分词设置 |
| __pycache__/、.pytest_cache/ | 运行与测试缓存，不是研究数据 |
| 本报告 | 项目说明、真实验证和面试准备；由 build_delivery_report.py 生成 |
| docs/file_inventory.json | 同一份逐文件用途的机器可读清单，便于搜索与后续维护 |

## 4. 数据、划分与真实实验

### 4.1 语料

| 编号 | 论文 | PDF 页数 | 片段数 | 固定版本 |
|---|---|---:|---:|---|
{source_rows}

合计 {len(index['sources'])} 篇、{sum(source['page_count'] for source in index['sources'])} 页、{index['chunk_count']} 个片段。
初期 qasper_embeddings.json 的 68 条向量仍然保留；新索引多了摘要边界和超长细分，不应拿两者行数直接比较。

原始 PDF 在 data/raw，来源文件保存下载入口、版本、SHA-256、获取记录和许可链接。论文许可独立于项目代码许可；未核实项明确标注。
文件哈希能检查所用副本，不能证明解析后的公式和表格语义正确。

18 个手工问题中，16 个有原页证据区间，2 个为拒答样本。它不是官方 QASPER 训练/测试划分。
标签按论文分离：QASPER/RAG 为 train，Attention 为 validation，Self-RAG 为 test。
全文索引包含全部演示文献；GEPA 的训练上下文另按相应论文限制，保留测试标签不进入反思或候选选择。

### 4.2 检索对照

固定 k=5，以下读取真实 [检索评测文件](../output/retrieval_evaluation.json)。

| 方法 | 正例数 | Hit@5 | 证据 Recall@5 | MRR@5 | P50 毫秒 | P95 毫秒 |
|---|---:|---:|---:|---:|---:|---:|
{metric_rows}

模型先预热，dense 和 hybrid 每条查询前清空查询缓存。这里不是冷启动或并发压测。
BM25 在这个小集合最好；人工给定的英文关键词、语料规模和题目设计都限制结论。
混合检索相对纯向量多命中 3/16 条，不能换算成真实用户问答正确率或宣称超过 BM25。

权重实验只用 train/validation。0.25、0.5 在验证召回上打平，0.75 更低；按预先确定的平局规则保留 0.5，未用测试标签挑参数。

### 4.3 真实 Qwen 冒烟

| 场景 | 实际状态 | 模型调用 | 返回 usage 的 token 数 | 局部检查 |
|---|---|---:|---:|---|
{live_rows}

读取 [真实接口验收](../output/live_smoke_results.json)。这些断言检查有限行为，不是盲评准确率。
可以打开 [摘要问答报告](../output/live_qasper/report.md)、[跨论文比较报告](../output/live_comparison/report.md)、[无关问题报告](../output/live_unrelated/report.md)。

较难的“何时检索”比较出现过被审核否决的情况，保留在 [回归目录](../output/regressions/comparison_timing)。
它说明召回、直接证据覆盖和审核尺度仍有改进空间；没有把保守拒答包装成完整回答。
初始嵌套 JSON 复制出错的诊断也保留了，最终采用 U 单元回填机制。

### 4.4 GEPA

实际记录：引擎样本评测 {gepa['metric_calls']} 次，保留候选 {gepa['candidate_count']} 个（包含基线），验证均分 {gepa['validation_scores']}。
最佳编号 {gepa['best_idx']}，仍为基线；保留测试基线 {gepa['heldout_baseline_score']:.3f}、所选策略 {gepa['heldout_candidate_score']:.3f}，未自动发布。
查看 [结果](../output/gepa_final/result.json)、[候选](../output/gepa_final/candidates.json)、[最佳提示词](../output/gepa_final/candidate_prompt.txt)。

适配器评分是 0.9×证据组召回 + 0.1×选择精度，不是最终回答准确率。
训练、验证、测试演示各只取两题。网络中断后恢复过引擎状态；result.json 的用量字段明确只统计最终这次调用，不是所有调试请求账单。
新候选出现过把训练编号与答案写入提示词的倾向，属于应检查的过拟合风险。本次验证没有提升，最优基线未被替换。
需要更大论文级隔离集、无答案样本与重复测量后，才能讨论泛化收益。

### 4.5 验收

- 本地行为测试：{tests} 项通过，依赖兼容性检查通过。
- 真实索引的原文区间、文件校验和、向量数值和摘要候选检查通过。
- 真实 HTTP 验收：{api.get('passed', False)}；任务、JSON/Markdown 下载与 SSE 重放见 [记录](../output/api_smoke.json)。
- Skill 的 quick_validate 通过；它只证明基本结构，不证明所有行为正确。
- 前端生产构建通过，已实际截图检查中文与布局。
- 项目源代码/报告扫描未发现本地 API 密钥；本地配置仍为明文私有文件，不等于生产密钥管理。

完整原始检查见 [acceptance.json](../output/acceptance.json)。

## 5. 面试资料范围

截至资料检索日，公开求职者自述会提到 RAG 流程、出错定位、上下文、固定评测、预算和任务交接等主题。
例如 [牛客公开自述](https://www.nowcoder.com/feed/main/detail/297fc651e816433e96f5a161ab6f8cd2?sourceSSR=post)。
此类帖子不能独立证实公司和面试过程，也不是成都岗位题目频率统计。

下面的问题由公开面经主题、官方文档和本项目实现推导，用来准备项目深挖。
技术答案优先依据原论文与官方资料；代码现状和实验结果以本地文件为准。没有把网络题库中的答案直接当成已实现能力。

## 6. {len(FAQ)} 个问题与回答

"""
    for i,(question,answer,where,links) in enumerate(FAQ,1):
        text+=f"### Q{i:02d}　{question}\n\n{answer}\n\n**代码/证据位置：** {where}。\n\n"
        if links:
            urls=links.split(" | ")
            text+="**参考：** "+ "、".join(f"[原始或官方资料 {j+1}]({url})" for j,url in enumerate(urls))+"。\n\n"
    text+="""## 7. 简历表述与自己的复习顺序

### 可以据实描述的内容

> 构建可溯源论文调研与证据核验工具，采用 LangGraph 编排有限研究流程，结合 BM25、E5 与 RRF 混合检索，支持摘要范围过滤、原文证据回填、审核及有限补查；使用 FastAPI、Vue 和 SQLite 实现任务进度、报告下载与实验记录，并完成小规模检索对照及 GEPA 提示词优化试验。

如果写数字，要连同范围：4 篇/355 片段、18 个手工问题、16 个检索正例。不能写成“官方 QASPER 准确率”“生产用户提升”“已实现通用自进化”“已采用 Chroma/Deep Agents/A2A”。
GEPA 本次没有展示提升，不写“优化后显著提高准确率”。

代码借助 AI 完成这一事实可以坦诚说明。面试前应亲自运行、调试和修改关键模块；尚未掌握的部分不要描述成自己独立设计并验证。

### 推荐学习路线

1. 用网页跑完三个示例，打开每份 evidence_packet/report/trace/run，解释它们之间的关系。
2. 从 retrieval.py 推导 BM25 与 RRF，手算 3 个片段的融合排序。
3. 在 grounding.py 看 U 编号如何映射成真实引用，运行虚构引用的失败测试。
4. 在 workflow.py 跟踪一次两轮重试，说明每个计数器何时变化、何时结束。
5. 读 evaluation.py，自己新增一个不同论文的问题与原文区间，再跑对照。
6. 读 API 和 SQLite 事件，用 Last-Event-ID 请求重放；解释为何这不等于业务图断点恢复。
7. 再读 GEPA adapter 和结果。先能解释为何本次没有提升，再谈改进计划。

### 现场演示前的检查

确认服务地址、模型接口可用；先预热一次；打开固定来源；准备成功与失败两类样例。
展示不足时说清“当前材料没确认”，不要临场改成没有出处的确定答案。

## 8. 后续工作的优先级

1. 扩大论文级隔离的人工证据集，增加多证据、冲突、图表依赖和无答案问题。
2. 对线上规划、材料选择与审核分别做回归和重复采样，区分召回失败、回答错误和误拒绝。
3. 做全文输入、不同 chunk/token 参数、Cross-Encoder reranker 对照；按质量/时间/成本决定是否采用。
4. 需要多人使用时，再补身份认证、文档权限、队列容量、取消/恢复、独立推理服务及服务监控。
5. 需要动态互联网研究时，再加论文检索/下载工具和来源验证；当前版本不自动搜索全网论文。

## 9. 主要原始资料

- [RAG 原论文](https://arxiv.org/abs/2005.11401v4)
- [Self-RAG 原论文](https://arxiv.org/abs/2310.11511v1)
- [Attention 原论文](https://arxiv.org/abs/1706.03762v7)
- [QASPER 官方论文页](https://aclanthology.org/2021.naacl-main.365/)
- [RRF 原论文](https://lintool.github.io/robust04-analysis-papers/p758-cormack.pdf)
- [Lucene BM25 官方实现](https://github.com/apache/lucene/blob/main/lucene/core/src/java/org/apache/lucene/search/similarities/BM25Similarity.java)
- [E5 模型说明](https://huggingface.co/intfloat/multilingual-e5-small)
- [Sentence Transformers 编码接口](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
- [LangGraph 图接口](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)
- [FastAPI 并发与异步](https://fastapi.tiangolo.com/async/)
- [MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [GEPA 项目](https://github.com/gepa-ai/gepa)
- [GEPA 原论文](https://arxiv.org/abs/2507.19457)
- [Ragas 原论文：评估维度参考，项目未使用其分数](https://arxiv.org/abs/2309.15217)
- [Lost in the Middle](https://arxiv.org/abs/2307.03172)
- [OpenAI Skills](https://developers.openai.com/plugins/concepts/skills)
- [MCP 官方说明](https://modelcontextprotocol.io/docs/getting-started/intro)
- [A2A 官方说明](https://a2a-protocol.org/latest/topics/what-is-a2a/)
- [OWASP 提示注入防护参考](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- [阿里云兼容接口说明](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- [公开面经线索：个人自述，非官方统计](https://www.nowcoder.com/feed/main/detail/297fc651e816433e96f5a161ab6f8cd2?sourceSSR=post)
"""
    if (ROOT/"output/ui-dashboard.png").exists():
        text+="\n## 附：本地页面预览\n\n![工作台预览](../output/ui-dashboard.png)\n"
    destination=ROOT/"docs/PROJECT_REPORT.zh-CN.md"
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(text,encoding="utf-8")
    (ROOT/"docs/file_inventory.json").write_text(json.dumps(
        [{"path":p,"purpose":purpose(p)} for p in code_paths+data_paths],ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"report":str(destination),"questions":len(FAQ),"listed_files":len(code_paths)+len(data_paths),
        "characters":len(text),"tests":tests,"local_acceptance":acceptance["passed"],"live_smoke":live["passed"]},ensure_ascii=False))

if __name__=="__main__":
    main()
