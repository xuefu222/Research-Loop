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
- 负对照：二元交叉熵。预期：保持段落对、损失公式和预算，打乱偏好关系后，正确排序所带来的增益应减弱。

**证伪条件** 在预设评估数据上，任一对照的Evidence F1差值（候选分数 − 对照分数）小于 0.5 百分点（F1 按 0–100 计），则预设收益主张未获支持。负对照异常也需要解释。

## 文献依据

- A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers（method，第 5.1 节，Evidence extraction，PDF 第 6 页）
  来源：https://aclanthology.org/2021.naacl-main.365.pdf#page=6
  摘录：we use a cross-entropy loss function with binary 0 or 1 gold labels
  比较：摘录明确二元分类目标，待检验方案使用成对分数间隔。其他成对排序先例仍需检索。

## 审查记录

- mechanism（pass）：变更细节明确且与目标紧密相连
- prior_art（uncertain）：无法从现有来源摘录断定该方法是否新颖
  - closest_source_id　没有提供足够的背景资料来判断是否有相似的工作 修改要求　查找更多文献以确认是否存在类似研究
- falsifiability（fail）：设定的具体阈值使结果可以被验证
  - experiment.negative_control　基线操作为 采用二元交叉熵损失训练；负对照操作为 同样使用二元交叉熵损失，但打乱正负样本对；机制干预为 成对排序损失中的相对评分原则。 修改要求　应设计一个真正失效核心机制的负对照
- feasibility（pass）：计划的操作步骤看起来是可以实施的

**负对照复核**
- 基线操作　采用二元交叉熵损失训练
- 负对照操作　同样使用二元交叉熵损失，但打乱正负样本对
- 使其失效的机制　成对排序损失中的相对评分原则
- 判断　invalid

## 实验进度

尚未运行小试。上面的判断来自材料和提案审查。

## 版本

- brief：85598212574fb9efa9842cf94a057b8bd2f2d08a6ca0c3b8c86bb1a440881c51
- candidate：86158e5ccff74db662a46919d4e68e1282d74679f786986251a3ed0547b3ccf7
- audit：86eb70ed93e7057a1c67e1bc9e82dc03d574c173a09b24bdbd38329783ed3065
