"""离线检索测试：人工向量验证算法，不代表真实语义检索质量。"""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import Mock, patch

import requests
import rag


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        cache = patch("rag._cache", None)
        cache.start()
        self.addCleanup(cache.stop)

    def test_real_documents_load(self):
        chunks = rag.load_knowledge()
        self.assertEqual({c["source"] for c in chunks},
                         {"steam_metrics.md", "attention_rules.md", "answer_guidelines.md"})
        for chunk in chunks:
            for key in ("source", "heading", "content", "title"):
                self.assertTrue(chunk[key])
        self.assertTrue(any(c["heading"] == "weeks_on_chart" for c in chunks))

    def test_heading_split_and_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch("rag.KNOWLEDGE_DIR", Path(directory)):
            with self.assertRaisesRegex(rag.RAGError, "知识库为空"):
                rag.load_knowledge()
            path = Path(directory) / "sample.md"
            path.write_text("# Title\nIntro\n## One\nFirst\n## Two\nLast\n", encoding="utf-8")
            chunks = rag.load_knowledge()
            self.assertEqual([c["heading"] for c in chunks], ["Title", "One", "Two"])
            self.assertEqual([c["content"] for c in chunks], ["Intro", "First", "Last"])
            self.assertTrue(all(c["title"] == "Title" and c["source"] == "sample.md" for c in chunks))
            path.write_text("# Empty\n## Also empty\n", encoding="utf-8")
            with self.assertRaises(rag.RAGError):
                rag.load_knowledge()

    @patch("rag.embed_texts")
    def test_invalid_query_and_k(self, embed):
        for query in (None, "", " ", 5):
            with self.assertRaisesRegex(ValueError, "query"):
                rag.retrieve(query)
        for k in (0, -1, True, 1.5, "3", None):
            with self.assertRaisesRegex(ValueError, "top_k"):
                rag.retrieve("test", k)
        embed.assert_not_called()

    def test_cosine(self):
        self.assertAlmostEqual(rag.cosine_similarity([3, 4], [1, 0]), 0.6)
        self.assertAlmostEqual(rag.cosine_similarity([1, 0], [-1, 0]), -1)
        self.assertAlmostEqual(rag.cosine_similarity([1, 0], [0, 1]), 0)

    def test_invalid_vectors(self):
        for vector in ([], [0, 0], [float("nan"), 1], [float("inf"), 1], [True, 0], ["1", 0], [1]):
            with self.assertRaises(rag.RAGError):
                rag.cosine_similarity([1, 0], vector)

    def test_ranking_cache_and_no_mutation(self):
        chunks = [{"source": "test.md", "title": "Test", "heading": str(i), "content": f"text {i}"}
                  for i in range(3)]
        original = deepcopy(chunks)
        with patch("rag.load_knowledge", return_value=chunks), patch("rag.embed_texts") as embed:
            embed.side_effect = [[[1, 0], [0, 1], [3, 4]], [[1, 0]], [[1, 0]],
                                 [[1, 0], [0, 1], [3, 4]], [[1, 0]]]
            result = rag.retrieve("query", 2)
            self.assertEqual([c["heading"] for c in result], ["0", "2"])
            self.assertAlmostEqual(result[1]["similarity"], 0.6)
            result[0]["content"] = "changed result"
            self.assertEqual(chunks, original)
            self.assertEqual(len(rag.retrieve("another query", 100)), 3)
            self.assertEqual(embed.call_count, 3)  # 一次文档，两次 query。
            chunks[0]["content"] = "edited document"
            rag.retrieve("query")
            self.assertEqual(embed.call_count, 5)  # 内容改变重新嵌入文档。

    @patch("rag.embed_texts", side_effect=rag.RAGError("test failure"))
    def test_failed_embedding_not_cached(self, embed):
        with self.assertRaises(rag.RAGError):
            rag.retrieve("test")
        self.assertIsNone(rag._cache)


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        for patcher in (patch.dict(os.environ, {"SILICONFLOW_API_KEY": "test-only-key"}, clear=True),
                        patch("rag.load_dotenv")):
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("rag.requests.post")
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.post.return_value = Mock(status_code=200)

    def test_success_restores_index_order(self):
        self.post.return_value.json.return_value = {"data": [
            {"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}
        self.assertEqual(rag.embed_texts(["one", "two"]), [[1, 0], [0, 1]])
        self.post.assert_called_once_with(rag.EMBEDDING_URL,
            headers={"Authorization": "Bearer test-only-key"},
            json={"model": "BAAI/bge-m3", "input": ["one", "two"], "encoding_format": "float"},
            timeout=(10, 60), allow_redirects=False)

    def test_invalid_input(self):
        for value in ([], "text", [""], [None]):
            with self.assertRaises(ValueError):
                rag.embed_texts(value)
        self.post.assert_not_called()

    def test_missing_key(self):
        os.environ.pop("SILICONFLOW_API_KEY")
        with self.assertRaisesRegex(rag.RAGError, "SILICONFLOW_API_KEY"):
            rag.embed_texts(["test"])
        self.post.assert_not_called()

    def test_network_errors_safe(self):
        for error in (requests.Timeout("test-only-key"), requests.ConnectionError("test-only-key")):
            self.post.side_effect = error
            try:
                rag.embed_texts(["test"])
            except rag.RAGError:
                self.assertNotIn("test-only-key", traceback.format_exc())
            else:
                self.fail("应当报错")

    def test_http_error_safe(self):
        self.post.return_value.status_code = 401
        self.post.return_value.text = "test-only-key"
        with self.assertRaisesRegex(rag.RAGError, "HTTP 401") as caught:
            rag.embed_texts(["test"])
        self.assertNotIn("test-only-key", str(caught.exception))
        self.post.return_value.json.assert_not_called()

    def test_malformed_response(self):
        cases = [None, {}, {"data": []}, {"data": [{"index": 1, "embedding": [1]}]},
                 {"data": [{"index": 0, "embedding": [0]}]},
                 {"data": [{"index": 0, "embedding": ["test-only-key"]}]}]
        for data in cases:
            self.post.return_value.json.return_value = data
            with self.assertRaises(rag.RAGError) as caught:
                rag.embed_texts(["test"])
            self.assertNotIn("test-only-key", str(caught.exception))
        self.post.return_value.json.side_effect = ValueError("test-only-key")
        with self.assertRaises(rag.RAGError):
            rag.embed_texts(["test"])


if __name__ == "__main__":
    unittest.main()
