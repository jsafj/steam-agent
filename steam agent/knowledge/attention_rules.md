# 当前榜单关注信号规则

这些规则是本项目为了演示可解释榜单分析而定义的业务规则。
不是 Steam 官方规则、销量预测模型、爆款预测模型、购买建议或投资建议。

## top_rank

条件：rank <= 20，包含第 20 名。信号 top_rank 表示当前排名靠前。
这是本项目固定阈值，不是 Steam 官方标准。

## strong_rise

条件：rank_direction == "up" 并且 rank_change_value >= 10，包含上涨 10 位。
信号 strong_rise 表示 Steam 页面显示排名上涨明显。
不得推断上涨比较周期；new、same、down、unknown 不能产生这个信号。

## high

为什么游戏会被判断为重点关注？必须同时满足 top_rank 和 strong_rise：
rank <= 20，并且 rank_direction == "up"、rank_change_value >= 10。
此时 attention_level = high，含义是重点关注。
这只表示当前排名靠前和页面显示上涨明显两个项目规则信号同时存在。
不表示未来一定增长、成为爆款，不是推荐购买或商业投资建议。

## top_rank attention level

只满足 top_rank，不满足 strong_rise 时，attention_level = top_rank，含义是当前排名靠前。

## strong_rise attention level

只满足 strong_rise，不满足 top_rank 时，attention_level = strong_rise，含义是上涨信号明显。

## normal

两个规则都不满足时，attention_level = normal，表示当前规则下暂无强关注信号。
这不是对游戏质量或未来表现的评价。

## Weeks

Weeks 可以作为背景信息展示，只描述为 Steam 页面 Weeks 数值。
第一版 Weeks 不参与 attention_level 判断、评分或预测，不影响是否重点关注。
项目不使用权重、概率、置信度或 0–100 分公式。
