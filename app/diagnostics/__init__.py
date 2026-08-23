"""Read-only runtime diagnostics."""

from .latency_report import build_latency_report, render_latency_markdown

__all__ = ["build_latency_report", "render_latency_markdown"]
