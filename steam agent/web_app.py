"""本地 Flask 聊天入口；每个问题独立调用现有 Agent。"""
import logging
import os
import re

from flask import Flask, jsonify, render_template, request
from agent import run_agent

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024


def _safe_detail(text):
    """日志脱敏；不读取 .env 文件，不回显凭据、Header 或 payload。"""
    key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    if key:
        text = text.replace(key, "[REDACTED]")
    # 敏感字段后可能是整个字典或多行内容，保守隐藏后续内容。
    text = re.sub(r"(?is)(authorization|bearer|siliconflow_api_key|headers?|payload|\.env).*",
                  "[REDACTED sensitive details]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    return text


@app.after_request
def log_chat_status(response):
    if request.path == "/api/chat":
        print(f"[Web] /api/chat HTTP status: {response.status_code}", flush=True)
    return response


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/chat")
def chat():
    print("[Web] 收到 /api/chat 请求", flush=True)
    if not request.is_json:
        return jsonify(ok=False, error="请发送 JSON 格式的问题。"), 415
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error="请求格式不正确。"), 400
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify(ok=False, error="请输入非空的问题。"), 400
    print("[Web] 请求校验完成", flush=True)
    try:
        print("[Web] 正在调用 run_agent...", flush=True)
        answer = run_agent(message.strip())
        print("[Web] run_agent 调用成功", flush=True)
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Agent 返回空答案")
        return jsonify(ok=True, answer=answer)
    except Exception as error:
        # 不使用 exc_info=True：默认 traceback 可能包含源码中的敏感字面量。
        # 仅记录当前异常的栈位置，不展开被底层主动隐藏的异常链或局部变量。
        frames = ["Traceback (文件/行号/函数；省略源码与局部变量):"]
        tb = error.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            frames.append(f"  File {code.co_filename}, line {tb.tb_lineno}, in {code.co_name}")
            tb = tb.tb_next
        app.logger.error("[Web] %s: %s\n%s", type(error).__name__,
                         _safe_detail(str(error)), _safe_detail("\n".join(frames)))
        return jsonify(ok=False, error="本次分析失败，请稍后重试。"), 502


@app.errorhandler(413)
def too_large(error):
    return jsonify(ok=False, error="问题过长，请缩短后重试。"), 413


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=False)
