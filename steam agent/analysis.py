"""纯 Python 榜单分析：只使用传入的 Snapshot，不联网、不读写文件。"""

from copy import deepcopy
from datetime import datetime


# 本项目固定规则，不是 Steam 官方标准；Weeks 不参与判断。
TOP_RANK_THRESHOLD = 20
STRONG_RISE_THRESHOLD = 10


def _validate_n(n):
    if type(n) is not int or n <= 0:
        raise ValueError("n 必须是正整数（不能是布尔值）。")


def _validate_snapshot(snapshot):
    """检查阶段 2 的数据约定，返回原游戏列表，仅供读取。"""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot 必须是字典。")
    for field in ("source_url", "fetched_at", "region"):
        if not isinstance(snapshot.get(field), str) or not snapshot[field].strip():
            raise ValueError(f"snapshot.{field} 必须是非空字符串。")
    try:
        fetched_at = datetime.fromisoformat(snapshot["fetched_at"])
    except ValueError as exc:
        raise ValueError("snapshot.fetched_at 必须是 ISO 格式时间。") from exc
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("snapshot.fetched_at 必须带时区。")
    games = snapshot.get("games")
    if not isinstance(games, list) or not games:
        raise ValueError("snapshot.games 必须是非空列表。")
    if type(snapshot.get("count")) is not int or snapshot["count"] != len(games):
        raise ValueError("snapshot.count 必须是整数且等于 games 的长度。")

    ranks = set()
    for index, game in enumerate(games):
        location = f"snapshot.games[{index}]"
        if not isinstance(game, dict):
            raise ValueError(f"{location} 必须是字典。")
        rank = game.get("rank")
        if type(rank) is not int or rank <= 0:
            raise ValueError(f"{location}.rank 必须是正整数。")
        if rank in ranks:
            raise ValueError(f"{location}.rank 出现重复排名：{rank}。")
        ranks.add(rank)
        for field in ("game_name", "game_url", "price", "rank_change"):
            if not isinstance(game.get(field), str):
                raise ValueError(f"{location}.{field} 必须是字符串。")
        for field in ("game_name", "game_url"):
            if not game[field].strip():
                raise ValueError(f"{location}.{field} 不能为空。")
        weeks = game.get("weeks_on_chart")
        if type(weeks) is not int or weeks < 0:
            raise ValueError(f"{location}.weeks_on_chart 必须是非负整数。")
        direction = game.get("rank_direction")
        if direction not in ("up", "down", "new", "same", "unknown"):
            raise ValueError(f"{location}.rank_direction 不合法。")
        if "rank_change_value" not in game:
            raise ValueError(f"{location} 缺少 rank_change_value。")
        value = game["rank_change_value"]
        if direction in ("up", "down"):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{location}.rank_change_value 对于 up/down 必须是正整数。")
        elif direction == "same":
            if type(value) is not int or value != 0:
                raise ValueError(f"{location}.rank_change_value 对于 same 必须是整数 0。")
        elif value is not None:
            raise ValueError(f"{location}.rank_change_value 对于 new/unknown 必须是 None。")
    return games


def get_top_games(snapshot, n=10):
    """返回当前 rank 最小的前 n 条记录副本；不足 n 条则返回全部。"""
    _validate_n(n)
    games = _validate_snapshot(snapshot)
    return deepcopy(sorted(games, key=lambda game: game["rank"])[:n])


def get_top_rising_games(snapshot, n=10):
    """只比较 up 的幅度，不推断变化周期；同幅度按当前排名升序。"""
    _validate_n(n)
    games = _validate_snapshot(snapshot)
    rising = [game for game in games if game["rank_direction"] == "up"]
    ordered = sorted(rising, key=lambda game: (-game["rank_change_value"], game["rank"]))
    return deepcopy(ordered[:n])


def get_long_running_games(snapshot, n=10):
    """返回页面 Weeks 数值最高的前 n 条；不解释为连续上榜周数。

    同 Weeks 数值按当前 rank 升序排列。
    """
    _validate_n(n)
    games = _validate_snapshot(snapshot)
    ordered = sorted(games, key=lambda game: (-game["weeks_on_chart"], game["rank"]))
    return deepcopy(ordered[:n])


def get_new_games(snapshot):
    """返回页面标记为 New 的所有记录副本，按当前 rank 升序。"""
    games = _validate_snapshot(snapshot)
    new_games = [game for game in games if game["rank_direction"] == "new"]
    return deepcopy(sorted(new_games, key=lambda game: game["rank"]))


def get_games_to_watch(snapshot):
    """对全部记录添加关注信号、等级和理由，返回新列表；不是预测或购买建议。

    复用现有校验：up 却缺少有效幅度属于异常数据，明确报错，不猜测。
    """
    games = deepcopy(_validate_snapshot(snapshot))
    for game in games:
        top_rank = game["rank"] <= TOP_RANK_THRESHOLD
        strong_rise = (game["rank_direction"] == "up"
                       and game["rank_change_value"] >= STRONG_RISE_THRESHOLD)
        signals = []
        reasons = []
        if top_rank:
            signals.append("top_rank")
            reasons.append(f"当前排名位于 Top {TOP_RANK_THRESHOLD}")
        if strong_rise:
            signals.append("strong_rise")
            reasons.append(f"Steam 页面显示排名上涨至少 {STRONG_RISE_THRESHOLD} 位")
        if top_rank and strong_rise:
            level = "high"
        elif top_rank:
            level = "top_rank"
        elif strong_rise:
            level = "strong_rise"
        else:
            level = "normal"
            reasons.append("当前规则下暂无强关注信号")
        game.update(signals=signals, attention_level=level, reasons=reasons)
    level_order = {"high": 0, "top_rank": 1, "strong_rise": 2, "normal": 3}
    return sorted(games, key=lambda game: (level_order[game["attention_level"]], game["rank"]))
