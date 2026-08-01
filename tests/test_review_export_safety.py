"""Regression tests for the review export path.

A workout or exercise name comes straight from an uploaded CSV, and the review
Markdown is rendered to a PDF by xhtml2pdf, whose default resolver fetches
``<img src>`` targets over the network. Before these tests, a name like
``<img src="http://attacker/x">`` made the hosted container issue outbound
requests (measured: three GETs, query string included, PDF still returned).
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from iron_trail.coach import render
from iron_trail.coach.export.pdf import markdown_to_pdf

POISON_PATH = "/leak.png"


class _CountingHandler(BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        type(self).hits.append(self.path)
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def listener():
    """A real local HTTP server, so a fetch attempt cannot go unnoticed."""
    _CountingHandler.hits = []
    server = HTTPServer(("127.0.0.1", 0), _CountingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}{POISON_PATH}", _CountingHandler.hits
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _weekly_summary(exercise: str) -> dict:
    return {
        "week_label": "2026-W31",
        "week_start": "2026-07-27",
        "week_end": "2026-08-02",
        "session_count": 3,
        "total_volume_kg": 12000.0,
        "training_minutes": 180,
        "current_streak_days": 3,
        "longest_streak_days": 9,
        "push_pull_ratio": 1.1,
        "archetype_mix": {"Strength": 2},
        "exercise_top_e1rm": [{"exercise": exercise, "e1rm_kg": 100.0, "delta_kg": 2.0}],
        "plateau_callouts": [
            {
                "status": "plateaued",
                "exercise": exercise,
                "current_e1rm_kg": 100.0,
                "peak_e1rm_kg": 105.0,
                "days_since_pr": 30,
            }
        ],
    }


def test_exercise_names_cannot_smuggle_html_into_the_review() -> None:
    md = render.weekly_review_md(
        _weekly_summary('<img src="http://attacker.example/x.png">'),
        "Solid week.",
        personality="default",
    )

    assert "<img" not in md
    assert "&lt;img src=" in md


def test_pdf_export_never_fetches_a_remote_resource(listener) -> None:
    url, hits = listener
    md = render.weekly_review_md(_weekly_summary(f'<img src="{url}">'), "Solid week.")

    pdf = markdown_to_pdf(md, title="Weekly Review")

    assert pdf.startswith(b"%PDF")
    assert hits == [], f"PDF renderer fetched {hits}"


def test_pdf_export_blocks_html_injected_after_rendering(listener) -> None:
    """Defence in depth: even Markdown that already contains a live tag — LLM
    output, say — must not reach xhtml2pdf's resolver."""
    url, hits = listener

    pdf = markdown_to_pdf(f'# Review\n\n<img src="{url}">\n', title="Weekly Review")

    assert pdf.startswith(b"%PDF")
    assert hits == [], f"PDF renderer fetched {hits}"


def test_markdown_formatting_still_survives_the_escaping() -> None:
    md = "# Heading\n\n- **bold** item\n- _italic_ item\n\n| a | b |\n| - | - |\n| 1 | 2 |\n"

    pdf = markdown_to_pdf(md, title="Weekly Review")

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
