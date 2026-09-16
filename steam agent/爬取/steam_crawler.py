import requests
import pandas as pd
from bs4 import BeautifulSoup


# =========================
# 1. 请求 Steam 畅销榜页面
# =========================

url = "https://store.steampowered.com/charts/topselling/US"

response = requests.get(url)

print("请求状态码：", response.status_code)


# =========================
# 2. 解析网页 HTML
# =========================

soup = BeautifulSoup(response.text, "html.parser")

rows = soup.find_all("tr")

print("找到的 tr 数量：", len(rows))


# =========================
# 3. 提取榜单数据
# =========================

games = []

# rows[0] 是表头，所以从 rows[1:] 开始
for row in rows[1:]:
    cells = row.find_all("td")

    # 防止遇到结构异常的行
    if len(cells) < 6:
        continue

    rank = cells[1].get_text(" ", strip=True)
    game_name = cells[2].get_text(" ", strip=True)
    price = cells[3].get_text(" ", strip=True)
    rank_change = cells[4].get_text(" ", strip=True)
    weeks_on_chart = cells[5].get_text(" ", strip=True)

    # 提取游戏详情页链接
    game_link = cells[2].find("a")

    if game_link:
        game_url = game_link.get("href")
    else:
        game_url = ""

    games.append({
        "rank": rank,
        "game_name": game_name,
        "price": price,
        "rank_change": rank_change,
        "weeks_on_chart": weeks_on_chart,
        "game_url": game_url
    })


print("成功提取游戏数量：", len(games))


# =========================
# 4. 保存原始数据
# =========================

raw_df = pd.DataFrame(games)

raw_df.to_csv(
    "steam_top_100_raw.csv",
    index=False,
    encoding="utf-8-sig"
)


# =========================
# 5. 数据清洗函数
# =========================

def clean_price(price_text):
    """
    将价格字段转换成数字。

    Free To Play -> 0
    ¥4,980 -> 4980
    -54% ¥10,067 ¥4,598 -> 4598
    没有价格 -> None
    """

    if price_text == "Free To Play":
        return 0

    if "¥" in price_text:
        parts = price_text.split("¥")

        # 有折扣时取最后一个价格，也就是当前售价
        last_price = parts[-1]

        last_price = last_price.replace(",", "").strip()

        return int(last_price)

    return None


def clean_rank_change(change_text):
    """
    拆分排名变化字段。

    ▲ 6 -> up, 6
    ▼ 7 -> down, 7
    New -> new, 0
    空值或无变化 -> same, 0
    """

    if "▲" in change_text:
        value = change_text.replace("▲", "").strip()
        return "up", int(value)

    elif "▼" in change_text:
        value = change_text.replace("▼", "").strip()
        return "down", int(value)

    elif "New" in change_text:
        return "new", 0

    else:
        return "same", 0


# =========================
# 6. 清洗数据
# =========================

clean_df = raw_df.copy()

clean_df["clean_price"] = clean_df["price"].apply(clean_price)

clean_df["is_free"] = clean_df["price"].apply(
    lambda x: 1 if x == "Free To Play" else 0
)

clean_df[["rank_direction", "rank_change_value"]] = (
    clean_df["rank_change"]
    .apply(lambda x: pd.Series(clean_rank_change(x)))
)


# =========================
# 7. 保存清洗后的数据
# =========================

clean_df.to_csv(
    "steam_top_100_clean.csv",
    index=False,
    encoding="utf-8-sig"
)


# =========================
# 8. 查看结果
# =========================

print(clean_df.head())

print("共保存：", len(clean_df), "条")