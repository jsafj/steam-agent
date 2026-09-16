"""实时读取 Steam 美国区畅销榜；不读取或写入 CSV。"""

import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


SOURCE_URL = "https://store.steampowered.com/charts/topselling/US"


class SteamRankingError(RuntimeError):
    """请求失败或页面无法可靠解析时抛出的错误。"""


def parse_rank_change(text):
    """返回 (方向, 幅度)；New 和未知值没有可计算的涨跌幅度。"""
    match = re.fullmatch(r"([▲▼])\s*([1-9][0-9]*)", text)
    if match:
        direction = "up" if match.group(1) == "▲" else "down"
        return direction, int(match.group(2))
    if text.casefold() == "new":
        return "new", None
    if text == "0":
        return "same", 0
    return "unknown", None


def _parse_ranking(html):
    """将本次响应的 HTML 转成游戏列表；结构异常时停止，不静默漏行。"""
    soup = BeautifulSoup(html, "html.parser")

    # 用表头定位榜单，避免把网页中的其他表格也当作榜单。
    tables = []
    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).casefold()
                   for th in table.find_all("th")]
        if [h for h in headers if h] == ["rank", "price", "change", "weeks"]:
            tables.append(table)
    if len(tables) != 1:
        raise SteamRankingError("未找到唯一的榜单表格：页面可能不是榜单，或表头结构已变化。")

    games = []
    for row in tables[0].find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if not cells and row.find("th"):
            continue  # 只跳过确认是表头的行。
        if len(cells) != 6:
            raise SteamRankingError(f"榜单行应有 6 个单元格，实际为 {len(cells)}。")

        # 复用原爬虫的单元格位置和 BeautifulSoup 文本提取方式。
        rank_text = cells[1].get_text(" ", strip=True)
        game_link = cells[2].find("a", href=True)
        price = cells[3].get_text(" ", strip=True)
        rank_change = cells[4].get_text(" ", strip=True)
        weeks_text = cells[5].get_text(" ", strip=True)

        if not re.fullmatch(r"[1-9][0-9]*", rank_text):
            raise SteamRankingError(f"排名不是有效正整数：{rank_text!r}")
        rank = int(rank_text)
        if game_link is None:
            raise SteamRankingError(f"第 {rank} 名缺少游戏链接。")
        game_name = game_link.get_text(" ", strip=True)
        href = game_link["href"].strip()
        game_url = urljoin(SOURCE_URL, href)
        parsed_url = urlparse(game_url)
        if (not game_name or not href
                or parsed_url.scheme != "https"
                or parsed_url.netloc != "store.steampowered.com"
                or not re.match(r"^/(app|sub|bundle)/[0-9]+(?:/|$)", parsed_url.path)):
            raise SteamRankingError(f"第 {rank} 名的名称或 Steam 商品链接异常。")

        # 第一版周数必须是非负整数；无法解释的原文写入错误，不猜测。
        if not re.fullmatch(r"[0-9]+", weeks_text):
            raise SteamRankingError(f"第 {rank} 名的上榜周数无法转换：{weeks_text!r}")
        direction, change_value = parse_rank_change(rank_change)
        games.append({
            "rank": rank,
            "game_name": game_name,
            "price": price,
            "rank_change": rank_change,
            "weeks_on_chart": int(weeks_text),
            "game_url": game_url,
            "rank_direction": direction,
            "rank_change_value": change_value,
        })

    # 目标页面是 Top 100；不足、重复或顺序异常都不能当作完整榜单。
    if [game["rank"] for game in games] != list(range(1, 101)):
        raise SteamRankingError(
            f"榜单不完整或排名异常：提取到 {len(games)} 条，预期为按顺序排列的 1–100 名。"
        )
    return games


def get_steam_ranking():
    """每次重新请求美国区榜单，返回来源、UTC 获取时间、地区、条数及游戏列表。

    无输入参数。不读写文件。失败时抛出 SteamRankingError，不使用旧数据兜底。
    fetched_at 是响应接收完成时间，不是 Steam 官方更新时间。
    """
    try:
        response = requests.get(
            SOURCE_URL,
            params={"l": "english"},  # 固定表头及 New 文案，便于验证结构。
            timeout=(10, 30),  # 连接超时、读取超时，单位为秒。
            headers={"Cache-Control": "no-cache"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SteamRankingError(f"实时请求 Steam 榜单失败：{exc}") from exc

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    final_url = urlparse(response.url)
    if (final_url.scheme != "https"
            or final_url.netloc != "store.steampowered.com"
            or final_url.path.rstrip("/") != "/charts/topselling/US"):
        raise SteamRankingError(f"请求被重定向到非预期页面：{response.url}")
    games = _parse_ranking(response.text)
    return {
        "source_url": response.url,
        "fetched_at": fetched_at,
        "region": "US",
        "count": len(games),
        "games": games,
    }


if __name__ == "__main__":
    # 导入文件不会发起请求；只有直接运行时才获取并打印预览。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        ranking = get_steam_ranking()
    except SteamRankingError as exc:
        print(f"获取失败：{exc}", file=sys.stderr)
        sys.exit(1)
    preview = {**ranking, "games": ranking["games"][:5]}
    print(json.dumps(preview, ensure_ascii=False, indent=2))
