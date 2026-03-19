"""
Web Crawler & Search Engine — Flask API + Dashboard

Endpoints:
  POST /index       — Start a crawl job {origin, k}
  GET  /search      — Search indexed pages ?q=...
  GET  /status      — System metrics (JSON)
  GET  /jobs        — List all crawl jobs
  DELETE /jobs/<id> — Cancel a crawl job
  GET  /            — Dashboard UI
"""

import logging
import signal
import sys

from flask import Flask, jsonify, request, send_from_directory

from crawler.storage import Storage
from crawler.indexer import Indexer
from crawler.searcher import Searcher

# ── Setup ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

storage = Storage()
indexer = Indexer(storage, max_workers=10, max_queue_depth=10_000, rate_per_domain=2.0)
searcher = Searcher(storage)


# ── Graceful shutdown ──

def handle_shutdown(signum, frame):
    logger.info("Shutting down — saving state...")
    indexer.save_state()
    storage.close()
    sys.exit(0)


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# ── API Routes ──

@app.route("/")
def dashboard():
    return send_from_directory("static", "index.html")


@app.post("/index")
def start_index():
    data = request.get_json(force=True)
    origin = data.get("origin", "").strip()
    k = data.get("k", 2)

    if not origin:
        return jsonify({"error": "origin URL is required"}), 400
    if not origin.startswith(("http://", "https://")):
        origin = "https://" + origin

    try:
        k = int(k)
    except (TypeError, ValueError):
        return jsonify({"error": "k must be an integer"}), 400

    if k < 0 or k > 10:
        return jsonify({"error": "k must be between 0 and 10"}), 400

    job = indexer.start_crawl(origin, k)
    logger.info(f"Started crawl job {job.job_id}: {origin} depth={k}")
    return jsonify({
        "job_id": job.job_id,
        "origin": origin,
        "max_depth": k,
        "status": "running",
    }), 201


@app.get("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "query parameter 'q' is required"}), 400

    results = searcher.search(query)
    return jsonify({
        "query": query,
        "count": len(results),
        "results": results,
    })


@app.get("/status")
def status():
    return jsonify(indexer.get_status())


@app.get("/jobs")
def list_jobs():
    return jsonify(storage.get_jobs())


@app.delete("/jobs/<int:job_id>")
def cancel_job(job_id):
    if indexer.cancel_job(job_id):
        return jsonify({"message": f"Job {job_id} cancelled"})
    # Maybe it's already finished
    storage.cancel_job(job_id)
    return jsonify({"message": f"Job {job_id} marked cancelled"})


@app.get("/jobs/<int:job_id>/resume")
def resume_job(job_id):
    job_info = storage.get_job(job_id)
    if not job_info:
        return jsonify({"error": "Job not found"}), 404

    job = indexer.start_crawl(
        job_info["origin"],
        job_info["max_depth"],
        resume_job_id=job_id,
    )
    return jsonify({
        "job_id": job.job_id,
        "origin": job_info["origin"],
        "max_depth": job_info["max_depth"],
        "status": "running",
        "resumed": True,
    })


# ── Main ──

if __name__ == "__main__":
    print("\n  Web Crawler & Search Engine")
    print("  Dashboard: http://localhost:8090\n")
    app.run(host="0.0.0.0", port=8090, debug=False, threaded=True)
