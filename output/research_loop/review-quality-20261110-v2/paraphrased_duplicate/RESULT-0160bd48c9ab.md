# 研究提案结果报告

**结论** 需要修订

**研究问题** 在 QASPER 的证据段落抽取任务中，保持 LED 编码器和段落打分头相同，用成对排序损失替换二元交叉熵，能否提高 Evidence F1？

**资源约束** 设计实验计划。保持数据划分、模型初始化和训练预算一致，测试集不调参。论文判断只依据给定摘录，数值结果留待实际运行。

## 判断依据

- prior_art · uncertain
- falsifiability · fail

## 提案

在固定 QASPER 划分上，成对排序相对两个 BCE 对照可提高 Evidence F1 至少 0.5 个百分点。

保持 LED 和段落打分头，固定每题采样的正负段落对，用 max(0, 1 - score_positive + score_negative) 损失替换 BCE。只在开发集选学习率，测试集一次评估。

## 小试计划

- 简单基线：二元交叉熵
- 最接近的对照：类别加权二元交叉熵
- 评估数据：固定的 QASPER 测试题和证据标签，开发集独立调参。
- 公平条件：相同模型初始化、段落集合、数据划分、优化步数，记录三组固定种子。
- 负对照：保持原来的二元交叉熵训练，再重复一遍基线配置。预期：保持段落对、损失公式和预算，打乱偏好关系后，正确排序所带来的增益应减弱。

**证伪条件** 在预设评估数据上，任一对照的Evidence F1差值（候选分数 − 对照分数）小于 0.5 百分点（F1 按 0–100 计），则预设收益主张未获支持。负对照异常也需要解释。

## 文献依据

- A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers（method，第 5.1 节，Evidence extraction，PDF 第 6 页）
  来源：https://aclanthology.org/2021.naacl-main.365.pdf#page=6
  摘录：we use a cross-entropy loss function with binary 0 or 1 gold labels
  比较：摘录明确二元分类目标，待检验方案使用成对分数间隔。其他成对排序先例仍需检索。

## 审查记录

- mechanism（pass）：提案中描述的机制是明确且可执行的。
- prior_art（uncertain）：最接近的基准来自QASPER文档，但该摘录未提供有关成对排序方法的具体信息或比较。
- falsifiability（fail）：提案设定了具体的改进目标（Evidence F1至少提高0.5个百分点），这使得结果可以被验证或反驳。
  - experiment.negative_control　基线操作为 使用类别加权二元交叉熵作为损失函数。；负对照操作为 继续使用原始的二元交叉熵训练，并重复基线配置。；机制干预为 未禁用特定机制。 修改要求　当前负向控制设计仅仅是重复基线，未能有效检验所提方法的独特贡献。一个有效的负向控制应该尝试破坏提案的关键假设之一，例如通过随机化正负样本标签来模拟无信息环境下的性能。
- feasibility（pass）：实验计划详细说明了如何保持模型初始化、数据划分等条件一致，确保了实验设计的有效性和技术上的可行性。

**负对照复核**
- 基线操作　使用类别加权二元交叉熵作为损失函数。
- 负对照操作　继续使用原始的二元交叉熵训练，并重复基线配置。
- 使其失效的机制　未禁用特定机制
- 判断　invalid

## 实验进度

尚未运行小试。上面的判断来自材料和提案审查。

## 版本

- brief：85598212574fb9efa9842cf94a057b8bd2f2d08a6ca0c3b8c86bb1a440881c51
- candidate：6db1d12acbfeb1b2a30e3985eeaa965413abcbf2257644352d23ebe58642593b
- audit：0160bd48c9ab0e521d4ca78c9532d70191319c80da346baf3055642732e8ee4b
