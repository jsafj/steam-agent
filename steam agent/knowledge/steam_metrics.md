# Steam 榜单字段与口径

本文件记录本项目已采用的谨慎口径，不补充未经验证的 Steam 官方定义。

## rank

rank 是 Steam Top Selling US 当前页面排名。项目仅处理这个地区的榜单。
不要描述为销量排名或销量件数排名，不得从排名推算售出数量。

## rank_change

rank_change 保留 Steam 当前页面显示的排名变化信息。
rank_direction 识别 up、down、same、new、unknown；unknown 不等于 same。
当 rank_direction 为 up 且 rank_change_value 为 N，只能说“Steam 页面显示排名上涨 N 位”。
比较周期尚未确认，不得自动解释为相比昨天、上周或上一期上涨 N 位。

## weeks_on_chart

weeks_on_chart 是 Steam 页面显示的 Weeks 数值。
只能说“Steam 页面 Weeks 数值为 N”。Weeks 能不能理解成连续上榜周数？目前不能。
项目尚未验证严格业务定义，不得说“连续上榜 N 周”或“连续畅销 N 周”。

## New

rank_direction 为 new 表示 Steam 当前页面将该条目标记为 New。
New 不是已经证实的新发行、刚刚发售、首次上榜或第一次进入榜单。
不要把页面标记扩展解释为发行时间或历史首次事件。

## fetched_at

fetched_at 是本程序成功获取当前 Steam 页面响应的时间，带时区。
它不是 Steam 官方榜单更新时间，也不能由它推断官方更新频率。
