"""
Runtime Agent Activity Tracker.

Unlike the 6 "development agents" (Research, Architect, Crawler, Search, UI,
Critic) — which ran during the build phase and produced the codebase — these
are SIX LIVE AGENTS that run during every crawl and every search. Each is a
distinct responsibility inside the running system, made observable.

Not a separate process — each "agent" is a thread-safe state record that the
indexer/searcher updates as work happens. The dashboard polls this state and
renders it live.

Why call them "agents"? Each has:
- A single responsibility (e.g., "deduplicate URLs")
- Observable state (current action + recent history)
- A public identity the UI shows to users

This is how we make the multi-agent architecture visible at runtime.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class AgentActivity:
    """Current state of one runtime agent."""

    name: str
    emoji: str
    description: str
    current_action: str = "idle"
    action_count: int = 0
    last_event_at: float = 0.0
    recent_events: deque = field(default_factory=lambda: deque(maxlen=20))


class RuntimeAgents:
    """Tracks the live state of 6 runtime agents during crawling and search.

    Thread-safe: all updates go through a single Lock. Reads return snapshots.

    The 6 runtime agents are:
    1. Fetcher Agent      - HTTP requests (shows: currently fetching URL)
    2. Parser Agent       - HTML → links/text (shows: tokens extracted)
    3. Indexer Agent      - TF-IDF index writes (shows: index entries written)
    4. Rate Limiter Agent - per-domain throttling (shows: throttled domain)
    5. Dedup Agent        - visited URL tracking (shows: visited set size)
    6. Search Agent       - query handling (shows: last query + result count)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._agents: dict[str, AgentActivity] = {
            "fetcher": AgentActivity(
                name="Fetcher Agent",
                emoji="📡",
                description="Makes HTTP requests with retry + SSL fallback",
            ),
            "parser": AgentActivity(
                name="Parser Agent",
                emoji="📄",
                description="Extracts links and text from HTML (stdlib html.parser)",
            ),
            "indexer": AgentActivity(
                name="Indexer Agent",
                emoji="📚",
                description="Writes TF-IDF entries to the inverted index",
            ),
            "ratelimiter": AgentActivity(
                name="Rate Limiter Agent",
                emoji="⏱️",
                description="Token-bucket per-domain politeness enforcement",
            ),
            "dedup": AgentActivity(
                name="Dedup Agent",
                emoji="🔁",
                description="Tracks visited URLs to prevent double-crawling",
            ),
            "search": AgentActivity(
                name="Search Agent",
                emoji="🔍",
                description="Scores queries against the inverted index",
            ),
        }

    def record(self, agent_key: str, action: str):
        """Record an event from an agent. O(1)."""
        with self._lock:
            agent = self._agents.get(agent_key)
            if agent is None:
                return
            agent.current_action = action
            agent.action_count += 1
            agent.last_event_at = time.time()
            agent.recent_events.append({"t": agent.last_event_at, "action": action})

    def snapshot(self) -> list[dict]:
        """Return current state of all agents as JSON-serializable list."""
        with self._lock:
            now = time.time()
            return [
                {
                    "key": key,
                    "name": a.name,
                    "emoji": a.emoji,
                    "description": a.description,
                    "current_action": a.current_action,
                    "action_count": a.action_count,
                    "seconds_since_event": round(now - a.last_event_at, 1)
                    if a.last_event_at
                    else None,
                    "is_active": a.last_event_at > 0 and (now - a.last_event_at) < 5.0,
                    "recent_events": [
                        {
                            "ago": round(now - e["t"], 1),
                            "action": e["action"],
                        }
                        for e in list(a.recent_events)[-5:]  # last 5
                    ],
                }
                for key, a in self._agents.items()
            ]


# Singleton — single runtime state shared across the process
runtime_agents = RuntimeAgents()
