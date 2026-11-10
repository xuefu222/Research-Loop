# TSK 固定实验

这些命令用于复跑已有的固定 TSK 实验和核查历史运行。新的研究提案使用同一 Skill 的 [提案到报告流程](run-contract.md)。

从包含 research_loop 目录的项目根目录运行 Python。使用项目现有环境，演示只需 Python 与 NumPy。

~~~powershell
$python = '.\.venv\Scripts\python.exe'
$entry = '.agents\skills\research-loop\scripts\run_research_loop.py'
$run = 'output\research_loop\my-first-demo'
& $python -X utf8 $entry demo --case 'examples\research_loop\tsk_overlap\case.json' --proposal 'examples\research_loop\tsk_overlap\proposal.json' --run $run
& $python -X utf8 $entry verify --run $run
~~~

## 输入与操作

- 案例 JSON 包含 title、question、adapter、materials。每份材料有 id、title、url、locator、excerpt。摘录来自实际读过的来源。
- 当前实验适配器是 tsk_overlap，使用合成的两规则时序回归流。为其他研究问题准备实验协议与适配器后再运行。
- 真实运行按 prepare、record、evaluate、report、verify 顺序。各阶段使用同一个全新运行目录。
- prepare 需要 --case。record 需要 --proposal，文件外层为 request_id 和 proposal。proposal 包含 hypothesis、mechanism、falsifier、nearby_work。nearby_work 中每个条目包含 source_id、quote、comparison。
- demo 接受不含外层 request_id 的预置提案。命令会完成全部阶段。预置提案用于演示，临时生成的提案走 prepare 与 record。

## 审查时看什么

- request.json 保存文献摘录、实验协议和代码摘要，proposal.json 绑定该请求。
- evaluation.json 保留验证和保留集的逐情景、逐种子结果。保留测试只评估验证阶段确定的候选。
- REPORT.md 由实际收据渲染。verify 检查提案引用、版本链与报告一致性。来源语义和研究新颖性需要原文审读。
- 阶段产物只发布一次。更换输入、代码或协议时创建新运行目录。
