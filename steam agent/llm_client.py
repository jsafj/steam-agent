"""最小 SiliconFlow 文本调用，与 Steam 数据获取和分析完全独立。"""

import os
import json
from pathlib import Path
import sys
from time import monotonic

import requests
from dotenv import load_dotenv


API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL = "Qwen/Qwen3.5-4B"
ENV_PATH = Path(__file__).resolve().parent / ".env"


class LLMError(RuntimeError):
    """配置、网络或 API 回复不符合预期。错误信息不包含请求凭据。"""


def ask_llm(prompt: str) -> str:
    """输入非空提示词，返回模型文本；失败时抛出 ValueError 或 LLMError。"""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt 必须是非空字符串。")
    message = chat_completion([{"role": "user", "content": prompt}])
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError("SiliconFlow 未返回非空文本回复。")
    return content.strip()


def chat_completion(messages, tools=None, tool_choice=None, enable_thinking=None):
    """发送消息列表，返回 assistant 消息（文本或 tool_calls）。不执行工具。"""
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages 必须是非空列表。")
    payload = {"model": MODEL, "messages": messages, "stream": False}
    if tools is not None:
        payload["tools"] = tools
        # 工具调用使用非思考模式，简化两次请求之间的消息传递。
        payload["enable_thinking"] = False
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
        if tool_choice == "none":
            print("[LLM] tool_choice: none", flush=True)

    # 仅统计工具回传请求的体积，不打印消息、系统提示或工具结果正文。
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    if tool_messages:
        print(f"[LLM] 回传请求统计：messages={len(messages)}，携带 tools={'tools' in payload}，tools 数量={len(payload.get('tools', []))}", flush=True)
        for index, message in enumerate(tool_messages, start=1):
            print(f"[LLM] Tool Result {index} JSON 字符数={len(message.get('content', ''))}", flush=True)
        print(f"[LLM] payload JSON 字符数（ensure_ascii=False）={len(json.dumps(payload, ensure_ascii=False))}，传输序列化字符数（ASCII 转义）={len(json.dumps(payload, ensure_ascii=True, allow_nan=False))}", flush=True)

    # 只从项目根目录加载；系统中已有的环境变量优先。
    print("[LLM] 正在加载本地 API 配置...", flush=True)
    load_dotenv(ENV_PATH, override=False, interpolate=False)
    api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    if not api_key or api_key == "your_api_key_here":
        print("[LLM] API Key 未配置或仍为占位值", flush=True)
        raise LLMError("请在环境变量或项目根目录 .env 中配置 SILICONFLOW_API_KEY。")

    started = monotonic()
    print("[LLM] 正在发送 HTTP 请求（连接超时 10 秒，读取超时 120 秒）...", flush=True)
    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=(10, 120),
            allow_redirects=False,
        )
    except requests.Timeout:
        print(f"[LLM] HTTP 请求超时，耗时 {monotonic() - started:.1f} 秒", flush=True)
        raise LLMError("SiliconFlow 请求超时，请稍后手动重试。") from None
    except requests.RequestException:
        print(f"[LLM] HTTP 网络请求失败，耗时 {monotonic() - started:.1f} 秒", flush=True)
        # 不拼接原异常：它可能包含请求信息或敏感内容。
        raise LLMError("SiliconFlow 网络请求失败，请检查网络、代理或连接设置。") from None

    print(f"[LLM] HTTP 响应接收完成，状态 {response.status_code}，耗时 {monotonic() - started:.1f} 秒", flush=True)
    if not 200 <= response.status_code < 300:
        hints = {
            400: "请检查请求参数及模型支持情况。",
            401: "请检查 API Key 是否有效。",
            403: "请检查账号及模型访问权限。",
            404: "请检查指定模型是否在账号中可用。",
            429: "请检查调用限额、余额或频率限制。",
        }
        hint = hints.get(response.status_code, "请检查服务状态或账号配置。")
        raise LLMError(f"SiliconFlow API 返回 HTTP {response.status_code}。{hint}")

    try:
        data = response.json()
        message = data["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMError("SiliconFlow 回复格式异常，缺少有效的 choices/message/content。") from None
    if not isinstance(message, dict):
        raise LLMError("SiliconFlow 回复格式异常，message 必须是对象。")
    print("[LLM] 响应消息解析完成", flush=True)
    # 整条消息脱敏，包括模型产生的参数；不记录原始响应。
    return json.loads(json.dumps(message, ensure_ascii=False).replace(api_key, "[REDACTED]"))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        print(ask_llm("请只回复：LLM API 连接成功"), flush=True)
    except (ValueError, LLMError) as error:
        print(f"调用失败：{error}", file=sys.stderr, flush=True)
        sys.exit(1)
