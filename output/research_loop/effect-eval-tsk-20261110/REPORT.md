# 高重叠 TSK 规则的短窗口后件更新

短历史窗口不能充分区分两条规则时，单独收缩规则差异方向，能否降低合成漂移流中的预测误差，同时控制其他情景的退步？

## 待检验的想法

当历史输入集中在两规则共同激活的区域，联合更新容易在历史难以区分的规则差异方向上吸收噪声。保留对共享方向的适应，同时收缩弱证据方向，可能对共享漂移有益，但可能延缓真实规则差异的变化。

将两条一阶 TSK 规则的参数转成共享和差异两个正交坐标。记窗口特征为 A 和 B，A 对应共享方向。先求共享岭更新，再用 Schur 补 S = BᵀB − BᵀA(AᵀA+λI)⁻¹AᵀB 衡量差异块的条件信息。对 S 的特征方向分别乘以 s/(s+τ)，最后用当前查询在这些方向上的响应生成预测。调整 τ 只用验证种子。

**预设反例**

如果主情景的 RMSE 改善不足预设门槛、无法超过最强的固定对照，或真实差异漂移等任一切片退步超限，则保留联合岭回归。全矩阵谱收缩和固定强岭是检验规则差异分解是否必要的对照。

## 已读证据与近邻

- FITSK: Online Local Learning With Generic Fuzzy Input Takagi–Sugeno–Kang Fuzzy Framework for Nonlinear System Estimation（PDF 第 1 页，引言）。经典 TSK 已研究局部与整体拟合的取舍。联合拟合是基线。 [原始材料](<https://sci2s.ugr.es/keel/pdf/specific/articulo/71-I.pdf>)
- Switching Linear Attention（第 3 节）。SwiLA 已用多个线性分量形成序列记忆。这里试验的是固定模糊前件后的条件谱收缩，没有复现其在线 EM。 [原始材料](<https://arxiv.org/html/2609.39034v1#S3>)
- SIFt-RLS: Subspace of Information Forgetting Recursive Least Squares（摘要）。方向选择已有成熟近邻。这里将规则差异对共享特征的条件信息用于窗口预测收缩，是否具有独立论文贡献需要再查证。 [原始材料](<https://arxiv.org/abs/2404.10844>)

## 固定协议与结果

验证使用 4 个种子，保留测试使用 6 个不同种子。每个情景每个种子预测 128 次。每步仅用此前 16 条已观测标签。
验证阶段确定候选 `contrast_gate_0.15`，保留测试只评估该候选与对照。指标为每条流的 RMSE 后按种子平均。
主情景需较联合岭回归改善至少 2%，同时优于该情景最强对照。任何情景相对联合岭回归的退步不能超过 2%。验证与保留测试都需要通过。

| 保留测试情景 | 联合岭 RMSE | 候选 RMSE | 相对变化（正值表示改善） |
|---|---:|---:|---:|
| overlap_shared | 0.26572 | 0.25818 | +2.84% |
| overlap_contrast | 0.18601 | 0.18430 | +0.92% |
| separated_shared | 0.30866 | 0.30209 | +2.13% |
| no_drift | 0.18599 | 0.18077 | +2.81% |

- **验证门槛** primary_gain_below_threshold、did_not_beat_strongest_primary_control。主情景最强对照为 `strong_ridge`。

- **保留测试门槛** did_not_beat_strongest_primary_control。主情景最强对照为 `strong_ridge`。

**决策** 未通过预设门槛，保留联合岭回归。本轮策略为 `joint_ridge`。

## 结论范围

数据由预定情景生成，长期参数使用合成模型已知初值。结果只适用于这批种子、数据生成过程与预设策略。
论文摘录只核查来源绑定。机制相似性仍需阅读方法全文判断，候选的论文新颖性仍待核实。保留结果中的负面切片，避免把主情景收益写成普遍提升。

## 运行记录

- 输入版本 `6a98dec0049f1e5be61e3e1696dc86ce16531e26cc7bf248612060ab5e951457`
- 提案版本 `f9740d3fa67e696088844ce5a9ae273ed6aee6164b4cee76831bbeb84508f84c`
- 实验版本 `d81e1423df560b177f315b7ea2ae393df55c5c79388741e7f13e30da05f725b2`
- 实验总耗时 1.914 秒，包含所有对照，不是单个方法的推理延迟。
