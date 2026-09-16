"""手动验证：实时获取一次 Snapshot，再执行四类分析。"""

import json
import sys

from analysis import (
    get_top_games,
    get_top_rising_games,
    get_long_running_games,
    get_new_games,
)
from steam_tool import SteamRankingError, get_steam_ranking


def main():
    try:
        snapshot = get_steam_ranking()  # 整个入口只有这一次获取。
        results = [
            ("当前排名 Top 10", get_top_games(snapshot, 10)),
            ("上涨幅度 Top 10（比较周期未确认）", get_top_rising_games(snapshot, 10)),
            ("Steam 页面 Weeks Top 10", get_long_running_games(snapshot, 10)),
            ("Steam 页面标记为 New 的游戏", get_new_games(snapshot)),
        ]
    except (SteamRankingError, ValueError) as exc:
        print(f"获取或分析失败：{exc}", file=sys.stderr)
        return 1

    print("以下四类分析共用同一次实时 Snapshot：")
    for field in ("source_url", "fetched_at", "region", "count"):
        print(f"{field}: {snapshot[field]}")
    print("fetched_at 是本程序获取时间，不是 Steam 官方更新时间。")
    for title, games in results:
        print(f"\n{title}（{len(games)} 条）")
        print(json.dumps(games, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
