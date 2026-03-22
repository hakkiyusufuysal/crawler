"""
Unit tests for the web crawler project.
Tests parser, tokenizer, storage, searcher, and API endpoints.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from crawler.parser import parse_html
from crawler.indexer import tokenize
from crawler.storage import Storage
from crawler.searcher import Searcher


class TestParser(unittest.TestCase):
    """Tests for HTML parsing and link extraction."""

    def test_extracts_title(self):
        html = "<html><head><title>My Page</title></head><body>hello</body></html>"
        title, text, links = parse_html(html, "https://example.com")
        self.assertEqual(title, "My Page")

    def test_extracts_body_text(self):
        html = "<html><body><p>Hello world</p></body></html>"
        _, text, _ = parse_html(html, "https://example.com")
        self.assertIn("Hello world", text)

    def test_strips_script_and_style(self):
        html = "<html><body><script>var x=1;</script><style>.a{}</style><p>visible</p></body></html>"
        _, text, _ = parse_html(html, "https://example.com")
        self.assertIn("visible", text)
        self.assertNotIn("var x=1", text)
        self.assertNotIn(".a{}", text)

    def test_extracts_links(self):
        html = '<html><body><a href="/page1">link1</a><a href="https://other.com/page2">link2</a></body></html>'
        _, _, links = parse_html(html, "https://example.com")
        self.assertIn("https://example.com/page1", links)
        self.assertIn("https://other.com/page2", links)

    def test_resolves_relative_urls(self):
        html = '<html><body><a href="../about">about</a></body></html>'
        _, _, links = parse_html(html, "https://example.com/blog/post")
        self.assertIn("https://example.com/about", links)

    def test_ignores_fragment_only_links(self):
        html = '<html><body><a href="#section">anchor</a></body></html>'
        _, _, links = parse_html(html, "https://example.com")
        # Fragment-only links should either be absent or resolve to base
        for link in links:
            self.assertNotIn("#", link)

    def test_empty_html(self):
        title, text, links = parse_html("", "https://example.com")
        self.assertEqual(title, "")
        self.assertEqual(links, [])


class TestTokenizer(unittest.TestCase):
    """Tests for the text tokenizer."""

    def test_basic_tokenization(self):
        tokens = tokenize("Hello World Python")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)
        self.assertIn("python", tokens)

    def test_removes_stop_words(self):
        tokens = tokenize("the cat is on the mat")
        self.assertNotIn("the", tokens)
        self.assertNotIn("is", tokens)
        self.assertNotIn("on", tokens)
        self.assertIn("cat", tokens)
        self.assertIn("mat", tokens)

    def test_filters_short_tokens(self):
        tokens = tokenize("I a x big cat")
        self.assertNotIn("i", tokens)
        self.assertNotIn("x", tokens)

    def test_lowercase(self):
        tokens = tokenize("PYTHON Django FLASK")
        self.assertIn("python", tokens)
        self.assertIn("django", tokens)
        self.assertIn("flask", tokens)

    def test_empty_string(self):
        self.assertEqual(tokenize(""), [])


class TestStorage(unittest.TestCase):
    """Tests for the SQLite storage layer."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.storage = Storage(Path(self.tmp.name))

    def tearDown(self):
        self.storage.close()
        os.unlink(self.tmp.name)

    def test_create_and_get_job(self):
        job_id = self.storage.create_job("https://example.com", 2)
        job = self.storage.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["origin"], "https://example.com")
        self.assertEqual(job["max_depth"], 2)
        self.assertEqual(job["status"], "running")

    def test_get_nonexistent_job(self):
        self.assertIsNone(self.storage.get_job(9999))

    def test_finish_job(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self.storage.finish_job(job_id, "completed")
        job = self.storage.get_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertIsNotNone(job["finished_at"])

    def test_cancel_job(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self.storage.save_frontier([("https://example.com/a", 1, job_id)])
        self.storage.cancel_job(job_id)
        job = self.storage.get_job(job_id)
        self.assertEqual(job["status"], "cancelled")
        # Frontier should be cleared
        frontier = self.storage.load_frontier(job_id)
        self.assertEqual(len(frontier), 0)

    def test_save_and_check_page(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self.assertFalse(self.storage.page_exists("https://example.com/page"))
        self.storage.save_page(
            "https://example.com/page", "Title", "Body text",
            ["https://example.com/link"], job_id, 0
        )
        self.assertTrue(self.storage.page_exists("https://example.com/page"))

    def test_total_pages(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self.assertEqual(self.storage.total_pages(), 0)
        self.storage.save_page("https://a.com", "A", "text", [], job_id, 0)
        self.storage.save_page("https://b.com", "B", "text", [], job_id, 1)
        self.assertEqual(self.storage.total_pages(), 2)

    def test_update_job_counts(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self.storage.update_job_counts(job_id, 42, 100)
        job = self.storage.get_job(job_id)
        self.assertEqual(job["pages_crawled"], 42)
        self.assertEqual(job["pages_queued"], 100)

    def test_get_jobs_ordered(self):
        self.storage.create_job("https://first.com", 1)
        self.storage.create_job("https://second.com", 2)
        jobs = self.storage.get_jobs()
        self.assertEqual(len(jobs), 2)
        # Most recent first
        self.assertEqual(jobs[0]["origin"], "https://second.com")

    def test_frontier_save_load_clear(self):
        job_id = self.storage.create_job("https://example.com", 2)
        items = [
            ("https://example.com/a", 1, job_id),
            ("https://example.com/b", 2, job_id),
        ]
        self.storage.save_frontier(items)
        frontier = self.storage.load_frontier(job_id)
        self.assertEqual(len(frontier), 2)
        urls = {url for url, _ in frontier}
        self.assertIn("https://example.com/a", urls)
        self.assertIn("https://example.com/b", urls)

        self.storage.clear_frontier(job_id)
        self.assertEqual(len(self.storage.load_frontier(job_id)), 0)

    def test_get_visited_urls(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self.storage.save_page("https://a.com", "A", "t", [], job_id, 0)
        self.storage.save_page("https://b.com", "B", "t", [], job_id, 1)
        visited = self.storage.get_visited_urls(job_id)
        self.assertEqual(visited, {"https://a.com", "https://b.com"})


class TestSearch(unittest.TestCase):
    """Tests for the inverted index and search functionality."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.storage = Storage(Path(self.tmp.name))
        self.searcher = Searcher(self.storage)

    def tearDown(self):
        self.storage.close()
        os.unlink(self.tmp.name)

    def _index_page(self, url, title, body, job_id, depth):
        """Helper to save a page and index its tokens."""
        self.storage.save_page(url, title, body, [], job_id, depth)
        title_tokens = tokenize(title)
        body_tokens = tokenize(body)
        entries = []
        from collections import Counter
        for token, count in Counter(title_tokens).items():
            entries.append((token, url, count / max(len(title_tokens), 1), "title"))
        for token, count in Counter(body_tokens).items():
            entries.append((token, url, count / max(len(body_tokens), 1), "body"))
        if entries:
            self.storage.save_index_entries(entries)

    def test_basic_search(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self._index_page("https://example.com/py", "Python Tutorial", "learn python programming", job_id, 0)
        result = self.searcher.search("python")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["relevant_url"], "https://example.com/py")

    def test_search_returns_triple_format(self):
        """Verify search returns (relevant_url, origin_url, depth) as required."""
        job_id = self.storage.create_job("https://origin.com", 3)
        self._index_page("https://origin.com/page", "Test Page", "test content", job_id, 2)
        result = self.searcher.search("test")
        self.assertGreater(result["total"], 0)
        item = result["results"][0]
        self.assertIn("relevant_url", item)
        self.assertIn("origin_url", item)
        self.assertIn("depth", item)
        self.assertEqual(item["origin_url"], "https://origin.com")
        self.assertEqual(item["depth"], 2)

    def test_title_boost(self):
        """Pages matching in title should score higher than body-only matches."""
        job_id = self.storage.create_job("https://example.com", 1)
        self._index_page("https://example.com/title", "Python Guide", "general programming", job_id, 0)
        self._index_page("https://example.com/body", "General Guide", "python programming", job_id, 0)
        result = self.searcher.search("python")
        self.assertEqual(result["total"], 2)
        # Title match should be first (higher score)
        self.assertEqual(result["results"][0]["relevant_url"], "https://example.com/title")

    def test_search_pagination(self):
        job_id = self.storage.create_job("https://example.com", 1)
        for i in range(10):
            self._index_page(f"https://example.com/p{i}", f"Page {i}", "python code", job_id, 0)

        # First page
        r1 = self.searcher.search("python", limit=3, offset=0)
        self.assertEqual(r1["total"], 10)
        self.assertEqual(len(r1["results"]), 3)
        self.assertEqual(r1["offset"], 0)

        # Second page
        r2 = self.searcher.search("python", limit=3, offset=3)
        self.assertEqual(len(r2["results"]), 3)
        self.assertEqual(r2["offset"], 3)

        # No overlap between pages
        urls1 = {r["relevant_url"] for r in r1["results"]}
        urls2 = {r["relevant_url"] for r in r2["results"]}
        self.assertEqual(len(urls1 & urls2), 0)

    def test_empty_query(self):
        result = self.searcher.search("")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["results"], [])

    def test_no_results(self):
        result = self.searcher.search("nonexistentterm")
        self.assertEqual(result["total"], 0)

    def test_multi_token_query(self):
        job_id = self.storage.create_job("https://example.com", 1)
        self._index_page("https://example.com/both", "Python Flask", "web framework tutorial", job_id, 0)
        self._index_page("https://example.com/one", "Python Only", "general programming", job_id, 0)
        result = self.searcher.search("python flask")
        # Page with both tokens should rank higher
        self.assertEqual(result["results"][0]["relevant_url"], "https://example.com/both")


class TestAPI(unittest.TestCase):
    """Tests for the Flask API endpoints."""

    def setUp(self):
        # Import app and configure for testing
        import app as app_module
        self.app = app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_dashboard_returns_html(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_search_requires_query(self):
        resp = self.client.get("/search")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("error", data)

    def test_search_with_query(self):
        resp = self.client.get("/search?q=test")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("results", data)
        self.assertIn("total", data)
        self.assertIn("offset", data)
        self.assertIn("limit", data)

    def test_status_endpoint(self):
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("active_jobs", data)
        self.assertIn("total_pages_indexed", data)
        self.assertIn("max_workers", data)

    def test_jobs_endpoint(self):
        resp = self.client.get("/jobs")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)

    def test_index_requires_origin(self):
        resp = self.client.post("/index", json={"k": 1})
        self.assertEqual(resp.status_code, 400)

    def test_index_validates_depth(self):
        resp = self.client.post("/index", json={"origin": "https://example.com", "k": 99})
        self.assertEqual(resp.status_code, 400)

    def test_index_validates_depth_type(self):
        resp = self.client.post("/index", json={"origin": "https://example.com", "k": "abc"})
        self.assertEqual(resp.status_code, 400)

    def test_resume_nonexistent_job(self):
        resp = self.client.get("/jobs/99999/resume")
        self.assertEqual(resp.status_code, 404)

    def test_search_pagination_params(self):
        resp = self.client.get("/search?q=test&limit=5&offset=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["limit"], 5)
        self.assertEqual(data["offset"], 10)

    def test_search_limit_capped(self):
        resp = self.client.get("/search?q=test&limit=999")
        data = resp.get_json()
        self.assertEqual(data["limit"], 200)


if __name__ == "__main__":
    unittest.main()
