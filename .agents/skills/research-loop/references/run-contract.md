# Research Loop 运行契约

这是仓库级 Skill。执行脚本调用同仓库的 `research_loop` 包。在 PowerShell 从项目根目录执行以下命令，使用项目自己的 Python 环境。

## 自动运行

准备一个 JSON 文件，使用下表 prepare 的字段。配置已有模型服务后，用一个新目录保存产物。

~~~powershell
$entry = '.agents\skills\research-loop\scripts\run_research_loop.py'
& '.\.venv\Scripts\python.exe' -X utf8 $entry agent --input 'brief-input.json' --run 'output\research_loop\first-agent-run'
~~~

加 `--plan-only` 时交付计划与审查。固定 TSK 样例可额外指定 `--pilot-adapter tsk_overlap`。适配器由命令行显式选择。模型收到研究问题、约束和经工具读取的摘录。结果路径由命令输出，`agent-trace.json` 保存阶段、工具名称和证据编号。

默认最多修订一轮，可用 `--max-revisions 0` 禁用，或设置为 2。设计检查未通过时，下一轮收到原提案、逐项问题和修改要求。每轮保存到 `revisions/01` 等新目录，`revision.json` 绑定上轮提案和审查版本。最终报告路径以命令返回值为准。修订提交失败时，返回上轮已审查的报告，并在轨迹中标记失败的修订目录。

自动修订适用于通用提案。固定 TSK 演示使用冻结的题目、机制和协议。提案调用遇到暂时性网络错误时，最多重试一次，并计入原有两次提案尝试上限。

补充本地证据需指定 `--retrieve`。可重复指定 `--doc-id qasper` 等编号。`--retrieval-scope abstract` 限定摘要，`full` 允许全文检索。每次最多补充三个片段，记录页码、字符位置和索引摘要。检索来源的 `full_text` 表示取自全文的指定片段，实际阅读范围由 excerpt 和 locator 给出。

## 手动运行

~~~powershell
$entry = '.agents\skills\research-loop\scripts\run_research_loop.py'
$python = '.\.venv\Scripts\python.exe'
$run = 'output\research_proposal\first-pass'
& $python -X utf8 $entry proposal prepare --run $run --input 'brief-input.json'
& $python -X utf8 $entry proposal candidate --run $run --input 'candidate-input.json'
& $python -X utf8 $entry proposal audit --run $run --input 'audit-input.json'
& $python -X utf8 $entry proposal finish --run $run
~~~

输入文件由宿主根据实际研究问题和已读材料生成。每次提交只接受下表列出的字段。

| 阶段 | 输入字段 | 产生的记录 |
| --- | --- | --- |
| prepare | question、constraints、sources。sources 的每项含 id、title、reference、locator、scope、excerpt | brief.json 保存材料与版本。scope 取 abstract、method、full_text 或 other |
| candidate | brief_id、hypothesis、mechanism、simple_baseline、closest_baseline、closest_source_id、comparisons、experiment | candidate.json 保存一个提案。brief_id 取 brief.json 的 id |
| audit | candidate_id、checks | audit.json 保存审查。candidate_id 取 candidate.json 的 id |
| status | 运行目录 | 输出当前状态、证伪条件和各阶段版本 |
| report | 运行目录 | 生成 RESULT-版本号.md。含结论、判断依据、文献、实验计划和已取得的实测结果 |
| pilot | 已通过审核且绑定适配器的运行目录 | 执行小试，保存 pilot.json 并生成结果报告 |
| finish | 运行目录 | 具备小试条件时执行实验，随后交付结果报告。缺实验条件时直接交付审查结果与计划 |

comparisons 中每项含 source_id、quote、relationship、reason。quote 必须是对应 excerpt 中连续出现的原文。relationship 取 distinct、same_mechanism 或 uncertain。closest_source_id 指向 comparisons 中最接近的工作。找不到可核对的最近工作时填写 null，并在交付中列出缺口。

experiment 包含 metric、unit、better、minimum_gain、evaluation_data、matched_conditions、negative_control、expected_control_behavior。better 取 higher 或 lower。minimum_gain 是与两个对照分别比较时，在原指标单位下要求的正收益差。若衡量相对提升，应先定义一个相对指标及其比较对象，再明确单位。负对照用于排查机制无效时也能产生看似正向收益的因素。

新版 Agent 提案自动标记 `design_version=2`，experiment 增加 controls。恰有三条记录，role 分别为 simple_baseline、closest_baseline 和 negative_control。每条包含 method、changed_factor、held_constant、expected。method 与对应的基线或负对照文字一致。单位采用明确的绝对分差或百分点。程序会阻止同名负对照与基线重复、单位仅为百分比的方案进入小试。含义相同但措辞不同的设计由审查角色判断。历史输入继续支持原字段格式。

checks 包含 mechanism、prior_art、falsifiability 和 feasibility。每项为含 status 与 basis 的对象。status 取 pass、uncertain 或 fail。basis 应说明审查证据、缺陷和需要调整的地方。机制审查关注信息从哪里来以及计算能否成立，近邻审查核对关键操作的重合，证伪审查关注公平对照和能推翻主张的观察，可行性审查核对预算和资源。由独立上下文完成这些判断，CLI 负责关联版本、检查结构与记录状态。

新版审查还可记录 issues，每项含 field、problem、correction。field 指向提案中的具体字段。存在未解决 issues 的检查不能标记 pass。修订应回应这些问题，证据不足的结论保留 uncertain。

Agent 审查还提交 control_review，分别记录 baseline_operation、negative_operation、disabled_mechanism、status 和 correction。status 为 valid、invalid 或 uncertain。程序会把 invalid 映射为证伪检查失败，uncertain 映射为未确定，防止其他检查的通过掩盖无效负对照。历史的仅含 checks 的审查文件仍可读取。

新运行依次进入 awaiting_candidate 和 awaiting_review。独立审查四项通过、最近工作有方法证据且记录了实质差异、比较中没有已记录的核心机制重合时，状态为 ready_for_pilot。其余审查结果返回 needs_revision 和原因。

## 小试结果

适配器目前只覆盖仓库自带的两规则 TSK 合成演示。启用时，候选输入增加 pilot_adapter=tsk_overlap。题目、假设和机制应直接采用项目演示 case.json 和 proposal.json 的值。simple_baseline 和 closest_baseline 使用 joint_ridge 与 strong_ridge。experiment 的 metric 和 unit 为 RMSE，better 为 lower，evaluation_data 为 synthetic_prequential，negative_control 为 no_drift。minimum_gain 是用户在审核前约定的绝对 RMSE 降幅。

审核通过后运行以下命令。程序比较两个对照和原适配器门槛，输出小试支持或未支持预设主张，并记录验证与保留测试的逐情景结果。协议和代码摘要随候选冻结，审核后发生变化需重新登记。报告版本随实际执行阶段变化，旧报告保留。

~~~powershell
& $python -X utf8 $entry proposal pilot --run $run
~~~

其他研究方向可使用 report 交付审查结果与实验计划。只有运行小试取得指标后才展示实测分数。

程序核验引用和已保存摘录的对应关系。外部来源真实性、语义和查新覆盖由采集与审查环节负责。CLI 可绑定审查版本，审查者独立性由宿主安排。旧运行文件保留，修改材料或提案时使用新运行目录。
