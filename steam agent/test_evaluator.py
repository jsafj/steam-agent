"""离线评测逻辑测试；不代表实际 Agent 效果。"""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import agent
from evals import evaluator as ev
from test_analysis import sample_snapshot
from test_agent import tool_call, tool_reply


def case(tools=None):
    return {"id": "test", "question": "测试问题", "expected_tools": tools or ["search_knowledge"],
            "forbidden_tools": [], "required_answer_terms": [],
            "forbidden_answer_patterns": [r"连续上榜\s*\d+\s*周"], "manual_review": False}


def trace(tools, fetch=0, rag=0, answer="模拟答案"):
    return {"answer": answer, "tools_called": [{"name": t, "arguments": {}} for t in tools],
            "steam_snapshot_fetch_count": fetch, "rag_call_count": rag, "runtime_error": None}


class EvaluatorTests(unittest.TestCase):
    def test_cases_load(self):
        cases = ev.load_cases()
        self.assertEqual(len(cases), 18)
        self.assertEqual({g: sum(c["category"] == g for c in cases)
                          for g in ("realtime", "knowledge", "mixed", "boundary")},
                         {"realtime": 5, "knowledge": 5, "mixed": 4, "boundary": 4})

    def test_tool_order_independent(self):
        names = ["get_steam_top_games", "search_knowledge"]
        self.assertTrue(ev.evaluate_case(case(names), trace(names[::-1], 1, 1))["tool_selection_correct"])

    def test_missing_tool(self):
        result = ev.evaluate_case(case(["get_steam_top_games"]), trace([]))
        self.assertIn("tool_selection", result["category"])

    def test_extra_tool(self):
        result = ev.evaluate_case(case(), trace(["search_knowledge", "get_steam_top_games"], 1, 1))
        self.assertIn("unnecessary_tool", result["category"])

    def test_forbidden_tool(self):
        c = case()
        c["forbidden_tools"] = ["get_steam_top_games"]
        self.assertTrue(ev.evaluate_case(c, trace(["get_steam_top_games"], 1))["forbidden_tool_violation"])

    def test_rag_snapshot_violation(self):
        self.assertFalse(ev.evaluate_case(case(), trace(["search_knowledge"], 1, 1))["snapshot_efficient"])

    def test_multiple_snapshot_violation(self):
        self.assertFalse(ev.evaluate_case(case(["get_steam_top_games"]),
                                         trace(["get_steam_top_games"], 2))["snapshot_efficient"])

    def test_rag_missing(self):
        self.assertIn("rag_missing", ev.evaluate_case(case(), trace([]))["category"])

    def test_boundary_negation_is_review_not_fail(self):
        good = ev.evaluate_case(case(), trace(["search_knowledge"], rag=1, answer="不能解释为连续上榜 10 周。"))
        self.assertFalse(good["boundary_failed"])
        self.assertTrue(good["manual_review"])
        bad = ev.evaluate_case(case(), trace(["search_knowledge"], rag=1, answer="游戏已连续上榜 10 周。"))
        self.assertTrue(bad["boundary_failed"])

    def test_badcase_append_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "badcases.json"
            path.write_text('[{"old": true}]', encoding="utf-8")
            ev.append_badcase({"case_id": "one"}, path)
            ev.append_badcase({"case_id": "two"}, path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data[0], {"old": True})
            self.assertEqual(len(data), 3)
            self.assertIn("timestamp", data[1])

    def test_invalid_history_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "badcases.json"
            path.write_text('{}', encoding="utf-8")
            with self.assertRaises(ValueError):
                ev.append_badcase({}, path)
            self.assertEqual(path.read_text(), '{}')

    def test_runtime_error_and_manual_review_summary(self):
        c = case()
        c["manual_review"] = True
        def fail(question):
            raise RuntimeError("test-only-secret")
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            path = Path(directory) / "badcases.json"
            report = ev.run_evaluation([c], runner=fail, badcase_path=path)
            self.assertEqual(report["summary"]["manual_review_required"], 1)
            self.assertEqual(report["summary"]["badcases"], 1)
            self.assertIn("runtime_error", report["results"][0]["category"])
            self.assertNotIn("test-only-secret", path.read_text(encoding="utf-8"))

    def test_pass_does_not_create_badcase(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            path = Path(directory) / "badcases.json"
            report = ev.run_evaluation([case()], lambda q: trace(["search_knowledge"], rag=1), path)
            self.assertEqual(report["summary"]["tool_selection_accuracy"], 1)
            self.assertFalse(path.exists())


class TraceTests(unittest.TestCase):
    def test_trace_mixed_counts_and_default_string(self):
        first = tool_reply(tool_call(), tool_call("search_knowledge", '{"query":"Weeks"}', "rag"))
        with patch("agent.chat_completion", side_effect=[first, {"content": "answer"}, {"content": "hello"}]), \
                patch("agent.get_steam_ranking", return_value=sample_snapshot()), \
                patch("agent.retrieve", return_value=[]), redirect_stdout(StringIO()):
            result = agent.run_agent_with_trace("test")
            self.assertEqual(result["steam_snapshot_fetch_count"], 1)
            self.assertEqual(result["rag_call_count"], 1)
            self.assertEqual(result["tools_called"][0]["arguments"], {"n": 5})
            self.assertEqual(result["tools_called"][1]["arguments"], {"query": "Weeks"})
            self.assertEqual(result["answer"], "answer")
            self.assertEqual(agent.run_agent("hello"), "hello")

    def test_failure_keeps_attempt_counts(self):
        with patch("agent.chat_completion", return_value=tool_reply(tool_call())), \
                patch("agent.get_steam_ranking", side_effect=agent.SteamRankingError("test-only-secret")), \
                redirect_stdout(StringIO()):
            result = agent.run_agent_with_trace("test")
        self.assertEqual(result["steam_snapshot_fetch_count"], 1)
        self.assertEqual(len(result["tools_called"]), 1)
        self.assertTrue(result["runtime_error"])
        self.assertNotIn("test-only-secret", str(result))

    def test_trace_pure_rag_no_steam(self):
        with patch("agent.chat_completion", side_effect=[tool_reply(tool_call("search_knowledge", '{"query":"Weeks"}')), {"content": "answer"}]), \
                patch("agent.retrieve", return_value=[]), patch("agent.get_steam_ranking") as fetch, redirect_stdout(StringIO()):
            result = agent.run_agent_with_trace("test")
        fetch.assert_not_called()
        self.assertEqual(result["rag_call_count"], 1)
        self.assertEqual(result["steam_snapshot_fetch_count"], 0)


if __name__ == "__main__":
    unittest.main()
