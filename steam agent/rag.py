"""独立语义检索：Markdown → 标题片段 → Embedding → 余弦相似度。"""

import json
import math
import os
from pathlib import Path
import re
import sys

import requests
from dotenv import load_dotenv


KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
ENV_PATH = Path(__file__).resolve().parent / ".env"
EMBEDDING_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBEDDING_MODEL = "BAAI/bge-m3"
_cache = None  # 只保存最近一次知识内容和对应向量，不写磁盘。


class RAGError(RuntimeError):
    """知识加载、Embedding 或向量计算失败。"""


def load_knowledge():
    """读取 knowledge/*.md；每个有正文的标题段为一块，保留来源和文档标题。"""
    chunks = []
    try:
        paths = sorted(KNOWLEDGE_DIR.glob("*.md"))
        for path in paths:
            title = path.stem
            heading = title
            body = []
            # 加一个结束标题，确保最后一段也被保存。
            lines = path.read_text(encoding="utf-8-sig").splitlines() + ["# END"]
            for line in lines:
                match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
                if match:
                    content = "\n".join(body).strip()
                    if content:
                        chunks.append({"source": path.name, "title": title,
                                       "heading": heading, "content": content})
                    if len(match.group(1)) == 1:
                        title = match.group(2)
                    heading = match.group(2)
                    body = []
                else:
                    body.append(line)
    except (OSError, UnicodeError):
        raise RAGError("知识文档读取失败，请检查 knowledge 目录和 UTF-8 编码。") from None
    if not chunks:
        raise RAGError("知识库为空：knowledge 中必须有带正文的 Markdown 文档。")
    return chunks


def _validate_vectors(vectors, count):
    if not isinstance(vectors, list) or len(vectors) != count or not vectors:
        raise RAGError("Embedding 向量数量与输入不一致。")
    dimension = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise RAGError("Embedding 向量不能为空。")
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension:
            raise RAGError("Embedding 向量维度不一致。")
        if any(type(x) not in (float, int) or not math.isfinite(x) for x in vector):
            raise RAGError("Embedding 向量必须包含有限数值。")
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise RAGError("Embedding 向量长度无效，不能计算余弦相似度。")


def embed_texts(texts):
    """一次批量请求返回与 texts 同顺序的向量列表；不调用对话模型。"""
    if (not isinstance(texts, list) or not texts
            or any(not isinstance(t, str) or not t.strip() for t in texts)):
        raise ValueError("texts 必须是非空字符串组成的非空列表。")
    load_dotenv(ENV_PATH, override=False, interpolate=False)
    key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    if not key or key == "your_api_key_here":
        raise RAGError("请配置环境变量或 .env 中的 SILICONFLOW_API_KEY。")
    try:
        response = requests.post(
            EMBEDDING_URL, headers={"Authorization": f"Bearer {key}"},
            json={"model": EMBEDDING_MODEL, "input": texts, "encoding_format": "float"},
            timeout=(10, 60), allow_redirects=False,
        )
    except requests.Timeout:
        raise RAGError("Embedding API 请求超时。") from None
    except requests.RequestException:
        raise RAGError("Embedding API 网络请求失败，请检查网络和代理。") from None
    if not 200 <= response.status_code < 300:
        raise RAGError(f"Embedding API 返回 HTTP {response.status_code}，请检查 Key、模型权限、额度或服务状态。")
    try:
        data = response.json()["data"]
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError()
        # 响应可能乱序，按 API 的 index 恢复输入顺序，拒绝重复或缺失。
        indices = [item["index"] for item in data]
        if any(type(i) is not int for i in indices) or sorted(indices) != list(range(len(texts))):
            raise ValueError()
        vectors = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
    except (ValueError, KeyError, TypeError):
        raise RAGError("Embedding API 回复格式异常或索引不完整。") from None
    _validate_vectors(vectors, len(texts))
    return vectors


def cosine_similarity(left, right):
    """余弦相似度 = 点积 / 两个向量长度的乘积；先归一化以避免乘积溢出。"""
    _validate_vectors([left, right], 2)
    left_norm, right_norm = math.hypot(*left), math.hypot(*right)
    value = sum((a / left_norm) * (b / right_norm) for a, b in zip(left, right))
    return max(-1.0, min(1.0, value))


def retrieve(query, top_k=3):
    """输入问题和正整数 K，返回按相似度降序排列的知识片段，不生成答案。"""
    global _cache
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 必须是非空字符串。")
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k 必须是正整数。")
    chunks = load_knowledge()
    texts = [f"{c['title']}\n{c['heading']}\n{c['content']}" for c in chunks]
    signature = (EMBEDDING_URL, EMBEDDING_MODEL, tuple(texts))
    if _cache is None or _cache[0] != signature:
        vectors = embed_texts(texts)
        _validate_vectors(vectors, len(chunks))
        _cache = (signature, vectors)  # 成功后才替换缓存；文档改变会自动重建。
    vectors = _cache[1]
    query_vectors = embed_texts([query])
    _validate_vectors(query_vectors, 1)
    results = [{**chunk, "similarity": cosine_similarity(vector, query_vectors[0])}
               for chunk, vector in zip(chunks, vectors)]
    return sorted(results, key=lambda result: result["similarity"], reverse=True)[:top_k]


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    query = " ".join(sys.argv[1:]) or "Weeks 能不能理解成连续上榜周数？"
    try:
        print(json.dumps(retrieve(query), ensure_ascii=False, indent=2))
    except (ValueError, RAGError) as error:
        print(f"检索失败：{error}", file=sys.stderr)
        sys.exit(1)
