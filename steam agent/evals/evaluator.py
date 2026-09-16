"""运行真实 Agent 评测；自动检查不等同于事实正确性验证。"""

import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from agent import run_agent_with_trace, TOOLS

CASES_PATH = Path(__file__).with_name("cases.json")
BADCASES_PATH = Path(__file__).with_name("badcases.json")


def load_cases(path=CASES_PATH):
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {t["function"]["name"] for t in TOOLS}
    ids = set()
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases 必须为非空列表。")
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or case["id"] in ids:
            raise ValueError("Case id 缺失或重复。")
        ids.add(case["id"])
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError("Case question 不能为空。")
        for field in ("expected_tools", "forbidden_tools"):
            if not isinstance(case.get(field), list) or any(t not in allowed for t in case[field]):
                raise ValueError("Case 工具列表不合法。")
        if set(case["expected_tools"]) & set(case["forbidden_tools"]):
            raise ValueError("期望工具和禁止工具不能重叠。")
        for pattern in case.get("forbidden_answer_patterns", []):
            re.compile(pattern)
    return cases


def check_boundary(answer, case):
    """仅将不带否定/引用迹象的明显断言标为失败，其他交给人工。"""
    failures = []
    review = bool(case.get("manual_review", False))
    for term in case.get("required_answer_terms", []):
        if term not in answer:
            failures.append(f"缺少要求的回答词：{term}")
    for sentence in re.split(r"[。！？!?\n]", answer):
        for pattern in case.get("forbidden_answer_patterns", []):
            if re.search(pattern, sentence, flags=re.I):
                if re.search(r"不|未|无法|不能|并非|否认|错误|误解|[‘’“”\"?？]", sentence):
                    review = True
                else:
                    failures.append("疑似违反回答口径：" + pattern)
    return failures, review


def evaluate_case(case, trace):
    actual = {c["name"] for c in trace["tools_called"]}
    expected = set(case["expected_tools"])
    forbidden = actual & set(case["forbidden_tools"])
    categories, reasons = [], []
    def fail(category, reason):
        if category not in categories:
            categories.append(category)
        reasons.append(reason)
    if actual != expected:
        fail("tool_selection", f"缺少工具：{sorted(expected - actual)}；多余工具：{sorted(actual - expected)}")
    if forbidden or actual - expected:
        fail("unnecessary_tool", "调用禁止或非预期工具。")
    rag_needed = "search_knowledge" in expected
    rag_used = "search_knowledge" in actual and trace["rag_call_count"] > 0
    if rag_needed and not rag_used:
        fail("rag_missing", "未执行要求的知识检索。")
    steam_used = any(t.startswith("get_steam_") for t in actual)
    fetches = trace["steam_snapshot_fetch_count"]
    efficient = fetches <= 1 if steam_used else fetches == 0
    # 成功的 Steam 执行应实际抓取一次；缺失工具由工具选择指标发现。
    if steam_used and not trace.get("runtime_error") and fetches != 1:
        efficient = False
    if not efficient:
        fail("snapshot_efficiency", "Snapshot 获取次数不符合当前工具执行要求。")
    boundary, review = check_boundary(trace["answer"], case)
    if boundary:
        fail("answer_boundary", "；".join(boundary))
    if trace.get("runtime_error") or not trace["answer"].strip():
        fail("runtime_error", "Agent 运行失败或未返回文本；不保存原始异常。")
    return {"case_id": case["id"], "question": case["question"],
            "expected_tools": sorted(expected), "actual_tools": sorted(actual),
            "answer": trace["answer"], "category": categories, "failure_reasons": reasons,
            "tools_requested": trace.get("tools_requested", []),
            "steam_snapshot_fetch_count": fetches, "rag_call_count": trace["rag_call_count"],
            "tool_selection_correct": actual == expected,
            "forbidden_tool_violation": bool(forbidden), "snapshot_efficient": efficient,
            "rag_needed": rag_needed, "rag_used": rag_used,
            "boundary_failed": bool(boundary), "manual_review": review}


def append_badcase(result, path=BADCASES_PATH):
    path = Path(path)
    history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not isinstance(history, list):
        raise ValueError("Badcase 历史格式错误，拒绝覆盖。")
    history.append({"timestamp": datetime.now(timezone.utc).isoformat(), **result})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_evaluation(cases, runner=None, badcase_path=BADCASES_PATH):
    runner = runner or run_agent_with_trace
    results = []
    for case in cases:
        print(f"[Eval] {case['id']}")
        try:
            trace = runner(case["question"])
        except Exception:
            trace = {"answer": "", "tools_called": [], "steam_snapshot_fetch_count": 0,
                     "rag_call_count": 0, "runtime_error": "执行失败"}
        result = evaluate_case(case, trace)
        results.append(result)
        if result["failure_reasons"]:
            append_badcase(result, badcase_path)
    total = len(results)
    correct = sum(r["tool_selection_correct"] for r in results)
    summary = {"total_cases": total, "tool_selection_correct": correct,
               "tool_selection_accuracy": correct / total if total else 0,
               "forbidden_tool_violations": sum(r["forbidden_tool_violation"] for r in results),
               "forbidden_tool_rate": sum(r["forbidden_tool_violation"] for r in results) / total if total else 0,
               "snapshot_efficiency_violations": sum(not r["snapshot_efficient"] for r in results),
               "rag_needed": sum(r["rag_needed"] for r in results),
               "rag_used_when_needed": sum(r["rag_needed"] and r["rag_used"] for r in results),
               "automatic_boundary_failures": sum(r["boundary_failed"] for r in results),
               "manual_review_required": sum(r["manual_review"] for r in results),
               "badcases": sum(bool(r["failure_reasons"]) for r in results)}
    return {"summary": summary, "results": results}


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    print("真实评测：逐条调用 Agent，可能产生聊天和 Embedding API 使用量；不自动重试。")
    try:
        report = run_evaluation(load_cases())
        output = CASES_PATH.parent / ("report_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print(f"完整结果及人工复核答案：{output}")
    except (OSError, ValueError):
        print("评测文件读取或保存失败，请检查格式与目录权限。", file=sys.stderr)
        sys.exit(1)
