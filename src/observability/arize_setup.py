"""Arize AX tracing setup for the UI Fraud Coordination Agent.

This module configures OpenTelemetry to export traces to Arize, with
auto-instrumentation for the google-genai SDK. Once initialized, every
Gemini call (including tool calls, reasoning steps, and responses) is
captured as a trace in the Arize dashboard.

Initialize once at process startup, before any agent code runs.
"""

import os
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


_initialized = False


def setup_arize_tracing(project_name: str = "ui-fraud-coordination-agent") -> None:
    """Initialize Arize tracing for the agent.

    Safe to call multiple times — only the first call takes effect.
    
    Args:
        project_name: The project identifier Arize uses to group traces.
            Default matches the GitHub repo name.
    """
    global _initialized
    if _initialized:
        return

    space_id = os.environ.get("ARIZE_SPACE_ID")
    api_key = os.environ.get("ARIZE_API_KEY")

    if not space_id or not api_key:
        raise RuntimeError(
            "ARIZE_SPACE_ID and ARIZE_API_KEY must be set in .env to enable tracing"
        )

    # Configure the OpenTelemetry exporter to point at Arize
    from arize.otel import register
    tracer_provider = register(
        space_id=space_id,
        api_key=api_key,
        project_name=project_name,
    )

    # Auto-instrument google-genai so every Gemini call produces a span
    from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
    GoogleGenAIInstrumentor().instrument(tracer_provider=tracer_provider)

    _initialized = True
    print(f"Arize tracing initialized for project: {project_name}")