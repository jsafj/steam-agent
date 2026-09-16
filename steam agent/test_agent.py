"""离线 Tool Calling 测试；复用人工 Snapshot，不访问任何真实服务。"""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
import traceback
import unittest
from unittest.mock import Mock, patch

import agent
import llm_client
from test_analysis import sample_snapshot


def tool_call(name="get_steam_top_games", arguments='{"n": 5}', call_id="call_1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}


def tool_reply(*calls):
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = sample_snapshot()
        self.patches = [patch("agent.chat_completion"),
                        patch("agent.get_steam_ranking", return_value=self.snapshot),
                        patch("agent.get_top_games", wraps=agent.get_top_games),
                        patch("agent.get_top_rising_games", wraps=agent.get_top_rising_games)]
        self.chat, self.fetch, self.top, self.rising = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.output = StringIO()
        redirect = redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        self.requests = []

    def responses(self, *replies):
        iterator = iter(replies)
        def respond(messages, tools=None, tool_choice=None, enable_thinking=None):
            self.requests.append(deepcopy(messages))
            return next(iterator)
        self.chat.side_effect = respond

    def test_top_and_tool_result(self):
        first = tool_reply(tool_call())
        self.responses(first, {"content": "最终模拟答案"})
        self.assertEqual(agent.run_agent("现在 Steam 前 5 名？"), "最终模拟答案")
        self.top.assert_called_once_with(self.snapshot, 5)
        self.rising.assert_not_called()
        self.fetch.assert_called_once_with()
        self.assertEqual(len(self.requests[0]), 2)
        self.assertEqual(self.requests[1][2], first)
        result_message = self.requests[1][3]
        self.assertEqual(result_message["role"], "tool")
        self.assertEqual(result_message["tool_call_id"], "call_1")
        result = json.loads(result_message["content"])
        self.assertEqual([g["rank"] for g in result["games"]], [1, 2, 3, 4, 5])
        for field in ("source_url", "fetched_at", "region", "count"):
            self.assertEqual(result[field], self.snapshot[field])
        self.assertEqual(result["returned_count"], 5)

    def test_rising(self):
        self.responses(tool_reply(tool_call("get_steam_top_rising_games", '{"n":3}')),
                       {"content": "模拟上涨结果"})
        agent.run_agent("上涨最多的 3 个游戏？")
        self.rising.assert_called_once_with(self.snapshot, 3)
        self.top.assert_not_called()
        result = json.loads(self.requests[1][-1]["content"])
        self.assertEqual([g["rank"] for g in result["games"]], [2, 3, 7])

    def test_default_n(self):
        self.responses(tool_reply(tool_call(arguments="{}")), {"content": "ok"})
        agent.run_agent("前几名")
        self.top.assert_called_once_with(self.snapshot, 10)

    def test_multiple_tools_share_snapshot_and_next_request_refreshes(self):
        first = tool_reply(tool_call(), tool_call("get_steam_top_rising_games", '{"n":3}', "call_2"))
        self.responses(first, {"content": "ok"}, first, {"content": "ok again"})
        agent.run_agent("两个榜单")
        self.assertEqual(self.fetch.call_count, 1)
        self.assertIs(self.top.call_args.args[0], self.rising.call_args.args[0])
        results = [json.loads(m["content"]) for m in self.requests[1] if m["role"] == "tool"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["fetched_at"], results[1]["fetched_at"])
        agent.run_agent("再查一次")
        self.assertEqual(self.fetch.call_count, 2)

    def test_direct_text(self):
        self.responses({"content": "你好"})
        self.assertEqual(agent.run_agent("你好"), "你好")
        self.fetch.assert_not_called()
        self.assertEqual(self.chat.call_count, 1)

    def test_invalid_user(self):
        for value in ("", " ", None, 5):
            with self.assertRaisesRegex(ValueError, "user_message"):
                agent.run_agent(value)
        self.chat.assert_not_called()

    def test_invalid_arguments(self):
        for args in ('bad json', '[]', 'null', '{"x":1}', '{"n":0}', '{"n":-1}',
                     '{"n":true}', '{"n":"3"}', '{"n":1.5}', '{"n":null}', None):
            with self.subTest(args=args):
                self.responses(tool_reply(tool_call(arguments=args)))
                with self.assertRaises(agent.AgentError):
                    agent.run_agent("test")
        self.fetch.assert_not_called()

    def test_unknown_tool_and_invalid_calls(self):
        for calls in ([tool_call(name="not_allowed")], [tool_call(call_id="")],
                      [tool_call(), tool_call()], [{}], "bad"):
            self.responses({"tool_calls": calls})
            with self.assertRaises(agent.AgentError):
                agent.run_agent("test")
        self.fetch.assert_not_called()

    def test_all_calls_validated_before_fetch(self):
        self.responses(tool_reply(tool_call(), tool_call(name="bad", call_id="call_2")))
        with self.assertRaises(agent.AgentError):
            agent.run_agent("test")
        self.fetch.assert_not_called()

    def test_failures_and_no_key_leak(self):
        secret = "test-only-secret"
        for stage in ("first", "steam", "final"):
            self.chat.side_effect = None
            self.fetch.side_effect = None
            if stage == "first":
                self.chat.side_effect = llm_client.LLMError(secret)
            elif stage == "steam":
                self.responses(tool_reply(tool_call()))
                self.fetch.side_effect = agent.SteamRankingError(secret)
            else:
                self.chat.side_effect = [tool_reply(tool_call()), llm_client.LLMError(secret)]
            try:
                agent.run_agent("test")
            except agent.AgentError:
                self.assertNotIn(secret, traceback.format_exc())
            else:
                self.fail("应当报错")
            self.assertNotIn(secret, self.output.getvalue())

    def test_missing_final_text_or_more_tools(self):
        for final in ({}, {"content": ""}, {"content": None}, tool_reply(tool_call()), None):
            self.responses(tool_reply(tool_call()), final)
            with self.assertRaises(agent.AgentError):
                agent.run_agent("test")

    def test_invalid_snapshot(self):
        self.fetch.return_value = {}
        self.responses(tool_reply(tool_call()))
        with self.assertRaisesRegex(agent.AgentError, "Snapshot"):
            agent.run_agent("test")

    def test_weeks_and_default_n(self):
        with patch("agent.get_long_running_games", wraps=agent.get_long_running_games) as weeks:
            for arguments, n in [('{"n":3}', 3), ('{}', 10)]:
                self.responses(tool_reply(tool_call("get_steam_long_running_games", arguments)),
                               {"content": "模拟 Weeks 回答"})
                self.assertEqual(agent.run_agent("Weeks 数值最高的游戏？"), "模拟 Weeks 回答")
                weeks.assert_called_with(self.snapshot, n)
                result = json.loads(self.requests[-1][-1]["content"])
                self.assertEqual([g["rank"] for g in result["games"]][:3], [5, 4, 2])

    def test_new_tool_without_n(self):
        with patch("agent.get_new_games", wraps=agent.get_new_games) as new:
            self.responses(tool_reply(tool_call("get_steam_new_games", '{}')),
                           {"content": "模拟 New 回答"})
            self.assertEqual(agent.run_agent("页面标记为 New 的游戏？"), "模拟 New 回答")
            new.assert_called_once_with(self.snapshot)
            result = json.loads(self.requests[-1][-1]["content"])
            self.assertEqual([g["rank"] for g in result["games"]], [1, 8])
            self.assertIn("无参数", self.output.getvalue())

    def test_new_rejects_parameters_before_any_fetch(self):
        for arguments in ('{"n":3}', '{"n":null}', '{"extra":1}', '[]', 'null'):
            self.responses(tool_reply(tool_call(), tool_call("get_steam_new_games", arguments, "new")))
            with self.assertRaisesRegex(agent.AgentError, "New Tool"):
                agent.run_agent("Top 和 New")
        self.fetch.assert_not_called()
        self.top.assert_not_called()

    def test_weeks_rejects_invalid_parameters(self):
        for arguments in ('{"n":0}', '{"n":true}', '{"n":-2}', '{"n":"3"}',
                          '{"n":2.5}', '{"n":null}', '{"extra":1}'):
            self.responses(tool_reply(tool_call("get_steam_long_running_games", arguments)))
            with self.assertRaises(agent.AgentError):
                agent.run_agent("Weeks")
        self.fetch.assert_not_called()

    def test_three_and_four_tools_correspond_to_ids_and_share_snapshot(self):
        with patch("agent.get_long_running_games", wraps=agent.get_long_running_games) as weeks, \
                patch("agent.get_new_games", wraps=agent.get_new_games) as new:
            for include_rising in (False, True):
                calls = [tool_call(arguments='{"n":2}', call_id="top"),
                         tool_call("get_steam_long_running_games", '{"n":3}', "weeks"),
                         tool_call("get_steam_new_games", '{}', "new")]
                expected = {"top": [1, 2], "weeks": [5, 4, 2], "new": [1, 8]}
                if include_rising:
                    calls.append(tool_call("get_steam_top_rising_games", '{"n":2}', "rising"))
                    expected["rising"] = [2, 3]
                self.fetch.reset_mock()
                self.responses(tool_reply(*calls), {"content": "综合模拟回答"})
                self.assertEqual(agent.run_agent("多个分析"), "综合模拟回答")
                self.fetch.assert_called_once_with()
                for function in (self.top, weeks, new):
                    self.assertIs(function.call_args.args[0], self.snapshot)
                if include_rising:
                    self.assertIs(self.rising.call_args.args[0], self.snapshot)
                messages = [m for m in self.requests[-1] if m["role"] == "tool"]
                self.assertEqual(len(messages), len(calls))
                for message in messages:
                    result = json.loads(message["content"])
                    self.assertEqual([g["rank"] for g in result["games"]], expected[message["tool_call_id"]])
                    for field in ("source_url", "fetched_at", "region", "count"):
                        self.assertEqual(result[field], self.snapshot[field])
            self.assertEqual(self.output.getvalue().count("正在获取 Steam 实时 Snapshot"), 2)
            self.assertIn("正在将 4 个工具结果返回模型", self.output.getvalue())

    def test_new_request_uses_new_snapshot_data(self):
        later = deepcopy(self.snapshot)
        later["fetched_at"] = "2026-09-15T13:00:00+00:00"
        self.fetch.side_effect = [self.snapshot, later]
        first = tool_reply(tool_call("get_steam_new_games", '{}'))
        self.responses(first, {"content": "first"}, first, {"content": "second"})
        agent.run_agent("New")
        agent.run_agent("再查 New")
        self.assertEqual(self.fetch.call_count, 2)
        for request_index, snapshot in [(1, self.snapshot), (3, later)]:
            result = json.loads(self.requests[request_index][-1]["content"])
            self.assertEqual(result["fetched_at"], snapshot["fetched_at"])

    def test_schema_exposes_six_distinct_tools(self):
        functions = {tool["function"]["name"]: tool["function"] for tool in agent.TOOLS}
        self.assertEqual(set(functions), {"get_steam_top_games", "get_steam_top_rising_games",
                                         "get_steam_long_running_games", "get_steam_new_games", "get_steam_games_to_watch", "search_knowledge"})
        for name, function in functions.items():
            parameters = function["parameters"]
            self.assertFalse(parameters["additionalProperties"])
            if name == "search_knowledge":
                self.assertEqual(set(parameters["properties"]), {"query"})
                self.assertEqual(parameters["properties"]["query"]["type"], "string")
                self.assertEqual(parameters["required"], ["query"])
            elif name in ("get_steam_new_games", "get_steam_games_to_watch"):
                self.assertEqual(parameters["properties"], {})
            else:
                n = parameters["properties"]["n"]
                self.assertEqual((n["type"], n["minimum"], n["default"]), ("integer", 1, 10))


    def test_watch_tool_rules_and_structured_results(self):
        with patch("agent.get_games_to_watch", wraps=agent.get_games_to_watch) as watch:
            self.responses(tool_reply(tool_call("get_steam_games_to_watch", '{}', "watch")),
                           {"content": "基于本项目当前规则得到的关注信号（模拟回答）"})
            answer = agent.run_agent("哪些游戏值得关注？")
            self.assertIn("本项目当前规则", answer)
            watch.assert_called_once_with(self.snapshot)
            self.fetch.assert_called_once_with()
            result_message = self.requests[-1][-1]
            self.assertEqual(result_message["tool_call_id"], "watch")
            result = json.loads(result_message["content"])
            self.assertEqual(result["rules"], {"top_rank_threshold": 20,
                                              "strong_rise_threshold": 10,
                                              "weeks_used_for_decision": False})
            self.assertEqual(result["games"], agent.get_games_to_watch(self.snapshot))
            self.assertEqual(result["returned_count"], self.snapshot["count"])
            for field in ("source_url", "fetched_at", "region", "count"):
                self.assertEqual(result[field], self.snapshot[field])

    def test_watch_and_top_share_snapshot_then_refresh(self):
        later = deepcopy(self.snapshot)
        later["fetched_at"] = "2026-09-15T14:00:00+00:00"
        self.fetch.side_effect = [self.snapshot, later]
        first = tool_reply(tool_call(arguments='{"n":5}', call_id="top"),
                           tool_call("get_steam_games_to_watch", '{}', "watch"))
        self.responses(first, {"content": "first"}, first, {"content": "second"})
        with patch("agent.get_games_to_watch", wraps=agent.get_games_to_watch) as watch:
            for index, snapshot in enumerate((self.snapshot, later)):
                agent.run_agent("Top 5 和值得关注的游戏？")
                self.assertEqual(self.fetch.call_count, index + 1)
                self.assertIs(self.top.call_args.args[0], snapshot)
                self.assertIs(watch.call_args.args[0], snapshot)
                messages = [m for m in self.requests[-1] if m["role"] == "tool"]
                self.assertEqual([m["tool_call_id"] for m in messages], ["top", "watch"])
                for message in messages:
                    self.assertEqual(json.loads(message["content"])["fetched_at"], snapshot["fetched_at"])

    def test_watch_parameters_cannot_change_rules(self):
        for arguments in ('{"n":3}', '{"attention_level":"high"}', '{"rank_threshold":5}',
                          '{"strong_rise_threshold":1}', '{"weight":0.5}', 'null', '[]'):
            self.responses(tool_reply(tool_call(), tool_call("get_steam_games_to_watch", arguments, "watch")))
            with self.assertRaisesRegex(agent.AgentError, "不接受参数"):
                agent.run_agent("值得关注")
        self.fetch.assert_not_called()
        self.top.assert_not_called()


    def knowledge_chunks(self):
        return [{"source": "steam_metrics.md", "heading": "New",
                 "content": "测试知识：New 不代表刚发行。", "similarity": 0.9}]

    def knowledge_call(self):
        return tool_call("search_knowledge", '{"query":"New 是不是刚发行？"}', "knowledge")

    def test_rag_only_no_snapshot(self):
        with patch("agent.retrieve", return_value=self.knowledge_chunks()) as retrieve:
            self.responses(tool_reply(self.knowledge_call()), {"content": "模拟知识回答"})
            self.assertEqual(agent.run_agent("New 是不是刚发行？"), "模拟知识回答")
            retrieve.assert_called_once_with("New 是不是刚发行？", top_k=3)
        self.fetch.assert_not_called()
        result_message = self.requests[-1][-1]
        self.assertEqual(result_message["tool_call_id"], "knowledge")
        self.assertEqual(json.loads(result_message["content"]),
                         {"query": "New 是不是刚发行？", "count": 1, "chunks": self.knowledge_chunks()})
        self.assertNotIn("正在获取 Steam", self.output.getvalue())
        self.assertNotIn("fetched_at:", self.output.getvalue())

    def test_invalid_rag_arguments_before_all_execution(self):
        with patch("agent.retrieve") as retrieve:
            for args in ('{}', '{"query":""}', '{"query":"  "}', '{"query":null}',
                         '{"query":5}', '{"query":"x","top_k":1}',
                         '{"query":"x","path":"file"}', '{"query":"x","model":"other"}'):
                self.responses(tool_reply(tool_call(), tool_call("search_knowledge", args, "knowledge")))
                with self.assertRaisesRegex(agent.AgentError, "search_knowledge"):
                    agent.run_agent("test")
            retrieve.assert_not_called()
        self.fetch.assert_not_called()

    def test_mixed_tools_both_orders(self):
        with patch("agent.retrieve", return_value=self.knowledge_chunks()):
            for rag_first in (True, False):
                self.fetch.reset_mock()
                calls = [tool_call("get_steam_new_games", '{}', "new"), self.knowledge_call()]
                if rag_first:
                    calls.reverse()
                self.responses(tool_reply(*calls), {"content": "混合答案"})
                self.assertEqual(agent.run_agent("现在有哪些 New，是什么意思？"), "混合答案")
                self.fetch.assert_called_once_with()
                messages = [m for m in self.requests[-1] if m["role"] == "tool"]
                self.assertEqual([m["tool_call_id"] for m in messages], [c["id"] for c in calls])
                results = {m["tool_call_id"]: json.loads(m["content"]) for m in messages}
                self.assertEqual(results["knowledge"]["chunks"], self.knowledge_chunks())
                self.assertEqual([g["rank"] for g in results["new"]["games"]], [1, 8])

    def test_two_steam_plus_rag_share_and_refresh(self):
        later = deepcopy(self.snapshot)
        later["fetched_at"] = "2026-09-15T15:00:00+00:00"
        self.fetch.side_effect = [self.snapshot, later]
        calls = tool_reply(tool_call(), self.knowledge_call(),
                           tool_call("get_steam_games_to_watch", '{}', "watch"))
        self.responses(calls, {"content": "one"}, calls, {"content": "two"})
        with patch("agent.retrieve", return_value=self.knowledge_chunks()), \
                patch("agent.get_games_to_watch", wraps=agent.get_games_to_watch) as watch:
            for index, snapshot in enumerate((self.snapshot, later)):
                agent.run_agent("Top 和值得关注，解释规则")
                self.assertEqual(self.fetch.call_count, index + 1)
                self.assertIs(watch.call_args.args[0], snapshot)
                self.assertIs(self.top.call_args.args[0], snapshot)
                messages = [m for m in self.requests[-1] if m["role"] == "tool"]
                self.assertEqual(len(messages), 3)
                result = json.loads(messages[-1]["content"])
                self.assertEqual(result["games"], agent.get_games_to_watch(snapshot))
                self.assertEqual(result["fetched_at"], snapshot["fetched_at"])

    def test_rag_failure_stops_without_key_leak(self):
        with patch("agent.retrieve", side_effect=agent.RAGError("test-only-secret")):
            self.responses(tool_reply(self.knowledge_call()))
            try:
                agent.run_agent("知识问题")
            except agent.AgentError as error:
                self.assertIn("RAG 知识检索失败", str(error))
                self.assertNotIn("test-only-secret", traceback.format_exc())
            else:
                self.fail("应该停止")
        self.fetch.assert_not_called()
        self.assertEqual(self.chat.call_count, 1)
        self.assertNotIn("test-only-secret", self.output.getvalue())

    def test_rag_failure_after_steam_does_not_summarize_partial_results(self):
        with patch("agent.retrieve", side_effect=agent.RAGError("test failure")):
            self.responses(tool_reply(tool_call(), self.knowledge_call()))
            with self.assertRaisesRegex(agent.AgentError, "RAG"):
                agent.run_agent("数据与知识")
        self.fetch.assert_called_once_with()
        self.assertEqual(self.chat.call_count, 1)

    def test_pure_steam_does_not_force_rag(self):
        with patch("agent.retrieve") as retrieve:
            self.responses(tool_reply(tool_call()), {"content": "Top 回答"})
            agent.run_agent("Top 5")
            retrieve.assert_not_called()
        self.fetch.assert_called_once_with()


class ChatTransportTests(unittest.TestCase):
    def test_performance_logs_and_lossless_tool_result(self):
        snapshot = sample_snapshot()
        calls = tool_reply(tool_call(arguments='{"n":5}'),
                           tool_call('search_knowledge', '{"query":"Weeks"}', 'rag'))
        chunks = [{'source': 'test.md', 'heading': 'Weeks', 'content': '测试知识', 'similarity': 0.8}]
        with patch('agent.chat_completion', side_effect=[calls, {'content': 'answer'}]) as chat, \
                patch('agent.get_steam_ranking', return_value=snapshot), \
                patch('agent.retrieve', return_value=chunks), \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(agent.run_agent('test'), 'answer')
        for label in ('第一次 LLM', 'Steam Snapshot', 'RAG', '第二次 LLM', 'run_agent 总耗时'):
            self.assertIn(f'[Perf] {label}:', output.getvalue())
        final_messages = chat.call_args.args[0]
        results = [m['content'] for m in final_messages if m['role'] == 'tool']
        steam_result = json.loads(results[0])
        self.assertEqual(steam_result['games'], agent.get_top_games(snapshot, 5))
        self.assertEqual(json.loads(results[1])['chunks'], chunks)
        self.assertLess(len(results[0]), len(json.dumps(steam_result, ensure_ascii=False)))

    def test_failure_still_logs_stage_and_total_time(self):
        with patch('agent.chat_completion', side_effect=agent.LLMError('test-only-secret')), \
                redirect_stdout(StringIO()) as output:
            with self.assertRaises(agent.AgentError):
                agent.run_agent('test')
        self.assertIn('[Perf] 第一次 LLM:', output.getvalue())
        self.assertIn('[Perf] run_agent 总耗时:', output.getvalue())
        self.assertNotIn('test-only-secret', output.getvalue())

    def test_explicit_non_thinking_without_tools_preserves_default(self):
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': 'answer'}}]}
        with patch.dict(os.environ, {'SILICONFLOW_API_KEY': 'test-only-key'}, clear=True), \
                patch('llm_client.load_dotenv'), \
                patch('llm_client.requests.post', return_value=response) as post, \
                redirect_stdout(StringIO()):
            messages = [{'role': 'user', 'content': 'test'}]
            llm_client.chat_completion(messages)
            self.assertNotIn('enable_thinking', post.call_args.kwargs['json'])
            llm_client.chat_completion(messages, tool_choice='none', enable_thinking=False)
            payload = post.call_args.kwargs['json']
            self.assertNotIn('tools', payload)
            self.assertIs(payload['enable_thinking'], False)
            self.assertEqual(payload['tool_choice'], 'none')
            self.assertEqual(post.call_args.kwargs['timeout'], (10, 120))

    def test_final_constraints_cover_reported_badcases(self):
        prompt = agent.FINAL_ANSWER_CONSTRAINTS
        for text in ("source_url、region、fetched_at", "region=US", "不得自行增加 Global",
                     "每次当前榜单查询都会重新获取 Snapshot", "仅在单次 run_agent",
                     "不得说用户无法实时刷新", "不新增不存在的游戏", "不重复生成同一记录",
                     "不得因游戏名称相似", "版本混乱", "数据异常", "修正名称",
                     "attention_level、signals、reasons", "Weeks 数值", "页面标记 New",
                     "不是预测、推荐购买或 Steam 官方评级", "简洁答案"):
            with self.subTest(text=text):
                self.assertIn(text, prompt)

    def test_final_constraints_preserve_watch_result_and_first_round(self):
        snapshot = sample_snapshot()
        snapshot['games'][0]['game_name'] = 'Similar Game'
        snapshot['games'][1]['game_name'] = 'Similar Game Edition'
        captured = []
        first = tool_reply(tool_call('get_steam_games_to_watch', '{}'))
        replies = [first, {'content': '模拟最终回答'}]
        def chat(messages, **kwargs):
            captured.append(deepcopy(messages))
            return replies.pop(0)
        with patch('agent.chat_completion', side_effect=chat), \
                patch('agent.get_steam_ranking', return_value=snapshot), redirect_stdout(StringIO()):
            self.assertEqual(agent.run_agent('哪些游戏值得关注？'), '模拟最终回答')
        self.assertEqual(captured[0][0]['content'], agent.SYSTEM_MESSAGE)
        self.assertNotIn(agent.FINAL_ANSWER_CONSTRAINTS, captured[0][0]['content'])
        self.assertIn(agent.FINAL_ANSWER_CONSTRAINTS, captured[1][0]['content'])
        self.assertEqual(captured[1][2], first)
        result = json.loads(captured[1][3]['content'])
        self.assertEqual(result['games'], agent.get_games_to_watch(snapshot))
        for field in ('source_url', 'region', 'fetched_at'):
            self.assertEqual(result[field], snapshot[field])

    def test_two_rounds_tool_choice_none_only_on_final_request(self):
        first = tool_reply(tool_call(arguments='{"n":5}'))
        payloads = []
        responses = [first, {"role": "assistant", "content": "模拟最终回答"}]

        def post(*args, **kwargs):
            payloads.append(deepcopy(kwargs["json"]))
            self.assertEqual(kwargs["timeout"], (10, 120))
            response = Mock(status_code=200)
            response.json.return_value = {"choices": [{"message": responses.pop(0)}]}
            return response

        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": "test-only-key"}, clear=True), \
                patch("llm_client.load_dotenv"), \
                patch("llm_client.requests.post", side_effect=post), \
                patch("agent.get_steam_ranking", return_value=sample_snapshot()), \
                redirect_stdout(StringIO()) as output:
            answer = agent.run_agent("现在 Steam Top 5 是什么？")

        self.assertEqual(answer, "模拟最终回答")
        self.assertEqual(len(payloads), 2)
        self.assertNotIn("tool_choice", payloads[0])
        self.assertEqual(payloads[1]["tool_choice"], "none")
        self.assertEqual(payloads[0]["tools"], agent.TOOLS)
        self.assertEqual(len(payloads[0]["tools"]), 6)
        self.assertNotIn("tools", payloads[1])
        for payload in payloads:
            self.assertFalse(payload["enable_thinking"])
            self.assertEqual(payload["model"], "Qwen/Qwen3.5-4B")
        self.assertEqual(payloads[0]["messages"][0]["content"], agent.SYSTEM_MESSAGE)
        self.assertEqual(payloads[1]["messages"][0]["content"],
                         agent.SYSTEM_MESSAGE + "\n\n" + agent.FINAL_ANSWER_CONSTRAINTS)
        self.assertEqual(payloads[1]["messages"][1], payloads[0]["messages"][1])
        self.assertEqual(payloads[1]["messages"][2], first)
        self.assertEqual(len(json.loads(payloads[1]["messages"][3]["content"])["games"]), 5)
        self.assertIn("[LLM] tool_choice: none", output.getvalue())

    def test_tool_message_transport_and_redaction(self):
        secret = "test-only-key"
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": tool_reply(tool_call())}]}
        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": secret}, clear=True), \
                patch("llm_client.load_dotenv"), \
                patch("llm_client.requests.post", return_value=response) as post:
            messages = [{"role": "user", "content": "test"}]
            reply = llm_client.chat_completion(messages, agent.TOOLS)
            self.assertEqual(reply["tool_calls"][0]["id"], "call_1")
            payload = post.call_args.kwargs["json"]
            self.assertEqual(payload["tools"], agent.TOOLS)
            self.assertEqual(payload["model"], "Qwen/Qwen3.5-4B")
            self.assertFalse(payload["enable_thinking"])
            response.json.return_value = {"choices": [{"message": {"content": secret}}]}
            self.assertNotIn(secret, str(llm_client.chat_completion(messages, agent.TOOLS)))


if __name__ == "__main__":
    unittest.main()
