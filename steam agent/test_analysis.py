"""阶段 3 离线测试；所有游戏都是人工构造的测试数据。"""

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from io import StringIO
import unittest
from unittest.mock import patch

import analysis
import main
from steam_tool import SteamRankingError


def sample_snapshot():
    # 刻意打乱排名，包含并列值和全部五种方向。
    specifications = [
        (6, "unknown", None, 2), (3, "up", 12, 40),
        (1, "new", None, 1), (7, "up", 5, 10),
        (5, "down", 80, 100), (2, "up", 12, 40),
        (8, "new", None, 1), (4, "same", 0, 90),
    ]
    games = []
    for rank, direction, value, weeks in specifications:
        games.append({
            "rank": rank, "game_name": f"Test game {rank}",
            "price": "", "rank_change": "测试原文",
            "weeks_on_chart": weeks, "game_url": f"https://example.com/{rank}",
            "rank_direction": direction, "rank_change_value": value,
        })
    return {"source_url": "https://example.com/test-only", "region": "US",
            "fetched_at": "2026-09-15T12:00:00+00:00", "count": len(games), "games": games}


FUNCTIONS = (analysis.get_top_games, analysis.get_top_rising_games,
             analysis.get_long_running_games, analysis.get_new_games)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = sample_snapshot()

    def test_ordering_and_filters(self):
        cases = [(analysis.get_top_games, [1, 2, 3, 4, 5, 6, 7, 8]),
                 (analysis.get_top_rising_games, [2, 3, 7]),
                 (analysis.get_long_running_games, [5, 4, 2, 3, 7, 6, 1, 8]),
                 (analysis.get_new_games, [1, 8])]
        for function, expected in cases:
            with self.subTest(function=function.__name__):
                self.assertEqual([g["rank"] for g in function(self.snapshot)], expected)
                if function != analysis.get_new_games:
                    self.assertEqual([g["rank"] for g in function(self.snapshot, 2)], expected[:2])
                    self.assertEqual(len(function(self.snapshot, 100)), len(expected))

    def test_snapshot_and_returned_records_are_independent(self):
        original = deepcopy(self.snapshot)
        for function in FUNCTIONS:
            result = function(self.snapshot)
            self.assertEqual(self.snapshot, original)
            result[0]["game_name"] = "changed by caller"
            self.assertEqual(self.snapshot, original)

    def test_no_matching_games(self):
        for game in self.snapshot["games"]:
            game.update(rank_direction="same", rank_change_value=0)
        self.assertEqual(analysis.get_new_games(self.snapshot), [])
        self.assertEqual(analysis.get_top_rising_games(self.snapshot), [])

    def test_invalid_n(self):
        for function in FUNCTIONS[:3]:
            for n in (0, -1, True, False, 1.5, "10", None):
                with self.subTest(function=function.__name__, n=n):
                    with self.assertRaisesRegex(ValueError, "n 必须是正整数"):
                        function(self.snapshot, n)

    def test_invalid_snapshots(self):
        cases = [(None, "snapshot"), ({}, "source_url")]
        for field, value, message in [
            ("games", [], "games"), ("games", {}, "games"),
            ("count", 100, "count"), ("count", True, "count"),
            ("fetched_at", "bad", "fetched_at"),
            ("fetched_at", "2026-09-15T12:00:00", "时区"),
        ]:
            bad = deepcopy(self.snapshot)
            bad[field] = value
            cases.append((bad, message))
        for field, value in [("rank", True), ("rank", "6"), ("rank", 0),
                             ("rank", 3), ("weeks_on_chart", None),
                             ("weeks_on_chart", -1), ("game_name", ""),
                             ("rank_direction", "invalid"), ("rank_change_value", 0)]:
            bad = deepcopy(self.snapshot)
            bad["games"][0][field] = value
            cases.append((bad, field))
        for field in self.snapshot["games"][0]:
            bad = deepcopy(self.snapshot)
            del bad["games"][0][field]
            cases.append((bad, field))
        for direction, value in [("up", None), ("up", True), ("down", -1), ("same", None)]:
            bad = deepcopy(self.snapshot)
            bad["games"][0].update(rank_direction=direction, rank_change_value=value)
            cases.append((bad, "rank_change_value"))
        for function in FUNCTIONS:
            for bad, message in cases:
                with self.subTest(function=function.__name__, message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        function(bad)

    @patch("main.get_steam_ranking")
    def test_main_fetches_once_and_shares_same_object(self, fetch):
        fetch.return_value = self.snapshot
        output = StringIO()
        with patch("main.get_top_games", wraps=analysis.get_top_games) as top, \
                patch("main.get_top_rising_games", wraps=analysis.get_top_rising_games) as rising, \
                patch("main.get_long_running_games", wraps=analysis.get_long_running_games) as weeks, \
                patch("main.get_new_games", wraps=analysis.get_new_games) as new, \
                redirect_stdout(output):
            self.assertEqual(main.main(), 0)
        fetch.assert_called_once_with()
        for function in (top, rising, weeks, new):
            self.assertEqual(function.call_count, 1)
            self.assertIs(function.call_args.args[0], self.snapshot)
        for field in ("source_url", "fetched_at", "region", "count"):
            self.assertIn(f"{field}: {self.snapshot[field]}", output.getvalue())

    @patch("main.get_steam_ranking", side_effect=SteamRankingError("test network failure"))
    def test_main_stops_on_fetch_failure(self, fetch):
        with patch("main.get_top_games") as top, redirect_stderr(StringIO()) as error:
            self.assertEqual(main.main(), 1)
        fetch.assert_called_once_with()
        top.assert_not_called()
        self.assertIn("test network failure", error.getvalue())


class WatchAnalysisTests(unittest.TestCase):
    def make_snapshot(self, rows):
        snapshot = sample_snapshot()
        template = snapshot["games"][0]
        snapshot["games"] = []
        for rank, direction, value in rows:
            game = deepcopy(template)
            game.update(rank=rank, game_name=f"Test {rank}", rank_direction=direction,
                        rank_change_value=value)
            snapshot["games"].append(game)
        snapshot["count"] = len(rows)
        return snapshot

    def test_boundaries_signals_and_reasons(self):
        cases = [(10, "up", 20, "high"), (20, "up", 10, "high"),
                 (21, "up", 10, "strong_rise"), (20, "up", 9, "top_rank"),
                 (21, "up", 9, "normal")]
        for rank, direction, value, level in cases:
            with self.subTest(rank=rank, value=value):
                game = analysis.get_games_to_watch(self.make_snapshot([(rank, direction, value)]))[0]
                self.assertEqual(game["attention_level"], level)
                expected_signals = []
                expected_reasons = []
                if rank <= 20:
                    expected_signals.append("top_rank")
                    expected_reasons.append("当前排名位于 Top 20")
                if value >= 10:
                    expected_signals.append("strong_rise")
                    expected_reasons.append("Steam 页面显示排名上涨至少 10 位")
                self.assertEqual(game["signals"], expected_signals)
                self.assertEqual(game["reasons"], expected_reasons or ["当前规则下暂无强关注信号"])

    def test_non_up_never_strong_rise(self):
        for direction, value in [("down", 100), ("same", 0), ("new", None), ("unknown", None)]:
            for rank, level in [(5, "top_rank"), (25, "normal")]:
                game = analysis.get_games_to_watch(self.make_snapshot([(rank, direction, value)]))[0]
                self.assertEqual(game["attention_level"], level)
                self.assertNotIn("strong_rise", game["signals"])

    def test_missing_up_value_rejected(self):
        with self.assertRaisesRegex(ValueError, "rank_change_value"):
            analysis.get_games_to_watch(self.make_snapshot([(10, "up", None)]))

    def test_weeks_does_not_change_decision_or_order(self):
        snapshot = self.make_snapshot([(21, "up", 10), (5, "up", 20), (30, "same", 0)])
        before = analysis.get_games_to_watch(snapshot)
        for game in snapshot["games"]:
            game["weeks_on_chart"] = 9999
        after = analysis.get_games_to_watch(snapshot)
        for first, second in zip(before, after):
            for field in ("rank", "signals", "attention_level", "reasons"):
                self.assertEqual(first[field], second[field])
            self.assertEqual(second["weeks_on_chart"], 9999)

    def test_sort_all_categories_and_rank_only(self):
        snapshot = self.make_snapshot([(40, "up", 200), (20, "up", 10), (10, "up", 11),
                                       (8, "same", 0), (5, "down", 100), (30, "up", 10),
                                       (60, "up", 9), (50, "up", 1)])
        games = analysis.get_games_to_watch(snapshot)
        self.assertEqual([g["rank"] for g in games], [10, 20, 5, 8, 30, 40, 50, 60])
        self.assertEqual([g["attention_level"] for g in games],
                         ["high", "high", "top_rank", "top_rank", "strong_rise", "strong_rise", "normal", "normal"])

    def test_input_preserved_and_results_independent(self):
        snapshot = sample_snapshot()
        original = deepcopy(snapshot)
        result = analysis.get_games_to_watch(snapshot)
        self.assertEqual(len(result), snapshot["count"])
        for game in result:
            source = next(g for g in original["games"] if g["rank"] == game["rank"])
            for field, value in source.items():
                self.assertEqual(game[field], value)
        result[0]["game_name"] = "changed"
        result[0]["signals"].append("changed")
        self.assertEqual(snapshot, original)

    def test_invalid_snapshot_rejected(self):
        for snapshot in (None, {}, {"games": []}):
            with self.assertRaises(ValueError):
                analysis.get_games_to_watch(snapshot)


if __name__ == "__main__":
    unittest.main()
