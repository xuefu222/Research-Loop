# Research Loop｜论文证据与可复现实验

Research Loop 从研究问题和已读论文出发，生成提案、审查和结果报告。LangGraph 编排流程，Deep Agents 执行提案与审查。用户可从 [Skill 入口](../.agents/skills/research-loop/SKILL.md) 或本地命令启动。

## 为什么这样做

用户先用论文调研模块找材料。Skill 根据已读证据提出一个假设，注明近邻与可反驳的条件。随后由程序执行固定协议，比较候选和强对照，按实际分数生成报告。用在面试中，可以展示从“找到论文”到“验证某项主张能不能成立”的完整过程。

设计借鉴了 idea-spark 的分阶段记录和可证伪假设，以及 nature-writing 按证据控制结论强度的写法。实际流程和产物由本项目自己的 Skill、CLI 和实验代码产生。

~~~mermaid
flowchart LR
    A["问题和论文摘录"] --> B["prepare 登记材料"]
    B --> C["draft 提案 Agent"]
    C -->|首次校验失败| C
    C -->|提案已登记| D["audit 审查 Agent"]
    C -->|仍无法登记| G["deliver 输出报告"]
    D -->|审核通过且有适配器| E["Python 执行固定小试"]
    D -->|可修复且有剩余轮次| H["补证据或修改设计"]
    H --> C
    D -->|轮次用尽或缺适配器| G
    E --> G
~~~

## 对照参考项目读代码

参考仓库使用 `create_deep_agent` 接入模型、系统提示词和工具。下面的链接指向本次查看的固定版本。建议从我们的 `main_agent.py` 开始，先看 `create_deep_agent(...)` 和紧接着的 `agent.invoke(...)`。

| 看哪部分 | 参考仓库 | 本项目 |
| --- | --- | --- |
| 组装 Agent | [agent/main_agent.py](https://github.com/xuefu222/deepagents/blob/56e6b1c6b7593c9d9b5298a464fb112cb47257d4/agent/main_agent.py) 用模型、提示词、工具组装主 Agent，再用 `astream` 推送网页进度 | [agent/main_agent.py](../research_loop/agent/main_agent.py) 用相同参数组装角色，CLI 用 `invoke` 取一次完整结果 |
| 接模型 | [agent/llm.py](https://github.com/xuefu222/deepagents/blob/56e6b1c6b7593c9d9b5298a464fb112cb47257d4/agent/llm.py) 用 `init_chat_model` 连接 OpenAI 兼容服务 | [agent/llm.py](../research_loop/agent/llm.py) 同样用 `init_chat_model`，复用项目的 Qwen 配置 |
| 写提示词 | [agent/prompts.py](https://github.com/xuefu222/deepagents/blob/56e6b1c6b7593c9d9b5298a464fb112cb47257d4/agent/prompts.py) 从 YAML 加载角色说明 | [agent/prompts.py](../research_loop/agent/prompts.py) 直接放两段短角色提示词 |
| 写工具 | [tools/travily_tool.py](https://github.com/xuefu222/deepagents/blob/56e6b1c6b7593c9d9b5298a464fb112cb47257d4/tools/travily_tool.py) 用 `@tool` 把搜索函数交给 Agent | [agent/tools.py](../research_loop/agent/tools.py) 用 `@tool` 注册证据读取、提案提交和四项审查提交 |

参考项目在 `subagents=[...]` 注册可委派角色，由主 Agent 决定何时调用。我们的 [agent_graph.py](../research_loop/agent_graph.py) 用 LangGraph 固定顺序，提案通过校验后才调用审查角色。两个角色用同一个 Qwen 配置，各自建立新对话和工具记录。审查者若未亲自读取最近工作的摘录，程序会拒绝它提交的近邻审查通过结论。[参考项目的子 Agent](https://github.com/xuefu222/deepagents/blob/56e6b1c6b7593c9d9b5298a464fb112cb47257d4/agent/subagents/network_search_agent.py)

## 验证与交付文件

| 位置 | 职责 |
| --- | --- |
| [SKILL.md](../.agents/skills/research-loop/SKILL.md) | 定义触发场景、工作流程和交付边界 |
| [agents/openai.yaml](../.agents/skills/research-loop/agents/openai.yaml) | Codex 界面显示的名称和简介 |
| [scripts/run_research_loop.py](../.agents/skills/research-loop/scripts/run_research_loop.py) | Skill 的执行入口，调用仓库的 Research Loop 命令 |
| [操作说明](../.agents/skills/research-loop/references/run-contract.md) | 输入字段、命令与审核范围 |
| [proposals.py](../research_loop/proposals.py) | 校验提案和引文、绑定审查版本、决定是否能执行小试并生成报告 |
| [artifacts.py](../research_loop/artifacts.py) | 读取 JSON、校验阶段版本、保存实验和报告文件 |
| [review.py](../research_loop/review.py) | 校验对照结构，检查负对照重复和收益单位 |
| [evidence.py](../research_loop/evidence.py) | 接入现有混合检索，绑定新增段落与来源位置 |
| [TSK 实验](../research_loop/experiment.py) | 生成数据流，实现六种对照与候选策略，执行验证、保留测试与决策 |
| [案例](../examples/research_loop/tsk_overlap/case.json) | 保存问题、出处、定位和已读的短摘录 |
| [预置提案](../examples/research_loop/tsk_overlap/proposal.json) | 保存演示用的假设、具体机制、反例和相关工作 |
| [测试](../tests/test_research_loop.py) | 核验伪造引文、过期提案、版本篡改、未来标签、基线公式和切片退步 |

## 如何复跑

配置好模型服务后，在 PowerShell 从仓库根目录执行。每次运行换一个空目录。终端会返回报告与阶段记录的路径。下面的示例允许审查通过后执行固定小试，改用自己的研究问题时替换输入文件并去掉适配器参数。

~~~powershell
$entry = '.agents\skills\research-loop\scripts\run_research_loop.py'
& '.\.venv\Scripts\python.exe' -X utf8 $entry agent --input 'examples\research_loop\tsk_overlap\brief.json' --run 'output\research_loop\my-agent-run' --pilot-adapter tsk_overlap
~~~

离线复跑预设实验见 [TSK 固定实验](../.agents/skills/research-loop/references/tsk-demo.md)。原有的 `python -m research_loop` 命令也可以直接执行。

对已有 PDF 可先使用仓库的混合检索得到候选原文。选择短摘录后仍要核对原文位置和阅读范围。要手动执行各阶段，可按运行契约执行 `proposal prepare`、`proposal candidate`、`proposal audit` 与 `proposal finish`。

每个阶段用内容摘要关联上一步。已有阶段结果不会被新提交覆盖。论文摘录、协议或实验代码变化后新建一次运行，旧结果仍能回查。SHA-256 用于识别内容变更与混用版本，适用范围是本地一致性核验。引文存在性与“引文是否支持主张”由不同环节处理，后者仍需要原文审查。

## 效果评测

新增的 [预标注审查案例](../evals/research_loop/audit_cases.json) 覆盖完全重复的负对照、换词描述的重复、单位含糊及合理的标签打乱干预。评测只计负对照和单位两个字段，记录漏检、误判和逐例审查结果。标签不会提供给模型，程序检测到的问题会按实际产品流程提供给审查角色。这四条属于开发案例，后续应按论文留出独立评测材料。

~~~powershell
& '.\.venv\Scripts\python.exe' -X utf8 'scripts\evaluate_research_review.py' --run 'output\research_loop\my-review-eval'
~~~

要观察完整修订过程，可在 agent 命令增加 `--retrieve --doc-id qasper --max-revisions 1`。同一轮审查收到冻结提案和证据，下一轮单独登记材料与提案。轨迹记录补充检索的索引版本和新增片段。

本轮开发评测包含三个预设问题和一个合理对照案例。加入结构化负对照复核后，模型识别了两个负对照问题，漏掉的单位问题由程序检查识别。合理的标签打乱案例在这两个评分字段上没有被误判。模型输出的问题召回率为 2/3，合并程序规则后为 3/3。四条均属于用于开发的案例，尚需按论文留出更大规模的独立评测。[逐例原始结果](../output/research_loop/review-quality-20261110-v2/summary.json) · [模型与规则分别计分](../output/research_loop/review-quality-20261110-v2/scored-summary.json)

真实闭环测试从仅含摘要的输入开始。混合检索补充了三个 QASPER 全文片段，修订阶段的提案与审查角色均实际读取了四份材料。一次引文校验失败后，提案在允许的重试中提交成功，生成第二轮报告并保留第一轮记录。最终仍为需要修订，新提案没有建立有效的近邻方法比较。[完整调用记录](../output/research_loop/revision-live-20261110-v3/agent-trace.json) · [修订后的报告](../output/research_loop/revision-live-20261110-v3/revisions/01/RESULT-e3448505e02a.md)

人工复核还发现，修订提案采用了完全移除训练损失的负对照，审查接受了这一设计。这会同时破坏整体训练，尚不足以隔离成对排序机制。当前程序可检查明确重复与单位问题，实验设计的语义质量仍需人工复核。

同一个 QASPER 问题分别提供方法段与摘要摘录，观察提案引文、审查状态、两个角色实际读取记录以及模型调用数。两组均使用已配置的模型服务和 `--plan-only`。输出包含每组的提案、审查、报告、阶段记录及汇总。输入来自 [QASPER 论文第 5.1 节](https://aclanthology.org/2021.naacl-main.365.pdf#page=6) 和 [论文摘要](https://aclanthology.org/2021.naacl-main.365/)。

~~~powershell
& '.\.venv\Scripts\python.exe' -X utf8 'scripts\evaluate_research_loop.py' --run 'output\research_loop\my-effect-eval'
~~~

2026-11-10 使用 Qwen Max 实跑。首轮两组都停在提案提交，改用带字段约束的提交工具并处理模型只回复文字的情况后，两组均保存了提案、审查和报告。每组最终复跑一次。

| 输入 | 引文命中原文 | 最近方法出处 | 近邻审查 | 模型调用 | 最终报告 |
| --- | --- | --- | --- | ---: | --- |
| 论文方法段 | 1/1 | 定位到 QASPER 的二元交叉熵方法 | 不确定，摘录不足以排查成对排序的其他先例 | 4 | [需要修订](../output/research_loop/effect-eval-20261110-v3/method/RESULT-2e600392384c.md) |
| 仅论文摘要 | 1/1 | 空 | 不确定，摘要只给出数据集信息 | 4 | [需要修订](../output/research_loop/effect-eval-20261110-v3/abstract/RESULT-3fcaeef8cfd0.md) |

两组的提案和审查角色均调用了证据工具。人工复核发现，方法段组把二元交叉熵同时用作基线和负对照，审查没有指出重复。这里测的是提案交付、引文和证据边界，QASPER 上的 Evidence F1 留待实际训练评估。[首轮汇总](../output/research_loop/effect-eval-20261110/summary.json) · [最终汇总](../output/research_loop/effect-eval-20261110-v3/summary.json)

## 模糊系统案例

假设短窗口中的输入长期集中在两个模糊规则共同激活的位置。此时共同变化可能容易估计，两个规则各自变化则难区分。实验将两个规则转为共享与差异坐标，按差异块在剔除共享影响后的谱信息控制更新强度。对照涵盖固定先验、仅共享更新、联合岭回归、强岭回归、固定收缩和对全矩阵做谱收缩。联合和局部拟合、固定状态的分量回归记忆与方向遗忘均有相关先例。当前试验用于定位一个具体问题，论文创新性仍需独立核查。[FITSK](https://sci2s.ugr.es/keel/pdf/specific/articulo/71-I.pdf) · [SwiLA](https://arxiv.org/html/2609.39034v1#S3) · [SIFt-RLS](https://arxiv.org/abs/2404.10844)

本次通过 Skill 脚本复跑，使用 4 个验证种子和 6 个保留种子，覆盖 4 个合成情景。保留测试主情景中，候选、默认联合岭和强岭对照的平均 RMSE 分别为 0.25818、0.26572 和 0.25373。候选相对默认基线降低 2.84%，强岭对照的误差更低。预设门槛要求候选同时优于强对照，因此程序保留联合岭回归。[复跑报告](../output/research_loop/effect-eval-tsk-20261110/REPORT.md) · [逐种子记录](../output/research_loop/effect-eval-tsk-20261110/evaluation.json)

## 面试中可以展示什么

先用一次正常运行展示主张和结果如何回到输入版本，再展示伪造引文或错误 request_id 被拒绝。最后指出候选虽然击败默认基线，却没有击败更强对照。面试可以围绕三个问题展开。

1. 为什么引文和实验结果都需要程序校验？引文要在实际摘录中找到，实验结果要由已执行协议产生，最后的报告直接读这两类记录。
2. 如何避免看完保留测试再调参数？候选在验证阶段确定，保留阶段只评估选定候选和预设对照，两阶段的种子不相交。
3. 策略会自动变好吗？系统只做有限离线候选评估并记录推荐或拒绝。应用层默认策略与自动上线仍需要单独治理。

当前仓库提供一个可运行的实验适配器，科研问题可以换材料，能否执行还取决于是否有对应的适配器和数据。既有 FastAPI 入口继续服务原论文问答流程，本次实验由本地 CLI 驱动。
