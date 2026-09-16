"""离线测试：全部 HTML 都是人工构造的测试夹具，不是真实 Steam 数据。"""

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import requests

from steam_tool import SOURCE_URL, SteamRankingError, get_steam_ranking, parse_rank_change


def sample_html():
    header = "<tr><th></th><th>Rank</th><th></th><th>Price</th><th>Change</th><th>Weeks</th></tr>"
    rows = []
    for rank in range(1, 101):
        rows.append(
            f'<tr><td></td><td>{rank}</td><td><a href="/app/{rank}/">'
            f'Test game {rank}</a></td><td>$19.99</td><td>▲ 6</td><td>4</td></tr>'
        )
    return "<table>" + header + "".join(rows) + "</table>"


def sample_response(html=None):
    return Mock(url=SOURCE_URL + "?l=english", text=sample_html() if html is None else html)


class SteamToolTests(unittest.TestCase):
    @patch("steam_tool.requests.get")
    def test_each_call_requests_and_returns_structured_data(self, get):
        get.return_value = sample_response()
        result = get_steam_ranking()
        get_steam_ranking()
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.args, (SOURCE_URL,))
        self.assertEqual(get.call_args.kwargs["timeout"], (10, 30))
        get.return_value.raise_for_status.assert_called()
        self.assertEqual(result["count"], 100)
        self.assertEqual(result["region"], "US")
        self.assertEqual(result["source_url"], get.return_value.url)
        self.assertIsNotNone(datetime.fromisoformat(result["fetched_at"]).tzinfo)
        self.assertEqual(result["games"][0], {
            "rank": 1, "game_name": "Test game 1", "price": "$19.99",
            "rank_change": "▲ 6", "weeks_on_chart": 4,
            "game_url": "https://store.steampowered.com/app/1/",
            "rank_direction": "up", "rank_change_value": 6,
        })

    def test_changes(self):
        cases = {"▲ 6": ("up", 6), "▼ 7": ("down", 7),
                 "New": ("new", None), "0": ("same", 0),
                 "": ("unknown", None), "?": ("unknown", None),
                 "▲ ?": ("unknown", None)}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_rank_change(text), expected)

    @patch("steam_tool.requests.get")
    def test_network_and_http_errors(self, get):
        for error in [requests.Timeout("test timeout"), requests.ConnectionError("test network")]:
            get.side_effect = error
            with self.assertRaises(SteamRankingError):
                get_steam_ranking()
        get.side_effect = None
        get.return_value = sample_response()
        get.return_value.raise_for_status.side_effect = requests.HTTPError("503 test")
        with self.assertRaises(SteamRankingError):
            get_steam_ranking()

    @patch("steam_tool.requests.get")
    def test_rejects_invalid_pages(self, get):
        html = sample_html()
        cases = ["", "<html>Access denied</html>",
                 html.replace("<th>Weeks</th>", "<th>Other</th>"),
                 html.replace("<td>100</td>", "<td>99</td>"),
                 html.replace("<td>4</td>", "<td>?</td>", 1),
                 html.replace("<td>1</td>", "<td>bad</td>", 1),
                 html.replace("Test game 1</a>", "</a>", 1),
                 html.replace('href="/app/1/"', 'href="https://example.com/"'),
                 html.replace("<td>$19.99</td>", "", 1),
                 html.split("<tr><td></td><td>100</td>")[0] + "</table>"]
        for page in cases:
            with self.subTest(page=page[:100]):
                get.return_value = sample_response(page)
                with self.assertRaises(SteamRankingError):
                    get_steam_ranking()

    @patch("steam_tool.requests.get")
    def test_unknown_change_preserved(self, get):
        get.return_value = sample_response(sample_html().replace("▲ 6", "unrecognized", 1))
        game = get_steam_ranking()["games"][0]
        self.assertEqual(game["rank_change"], "unrecognized")
        self.assertEqual(game["rank_direction"], "unknown")
        self.assertIsNone(game["rank_change_value"])

    @patch("steam_tool.requests.get")
    def test_rejects_redirect(self, get):
        get.return_value = sample_response()
        get.return_value.url = "https://store.steampowered.com/login/"
        with self.assertRaises(SteamRankingError):
            get_steam_ranking()


if __name__ == "__main__":
    unittest.main()
