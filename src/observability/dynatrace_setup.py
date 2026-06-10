"""Dynatrace distributed tracing setup.

Configures OpenTelemetry to export traces to Dynatrace via OTLP. Auto-
instruments pymongo (for MongoDB query traces) and requests (for HTTP traces).

This is complementary to Arize: Arize captures LLM reasoning traces via
OpenInference's google-genai adapter, while Dynatrace captures distributed
execution traces including database queries and external service calls.

Initialize once at process startup. Safe to call multiple times.
"""

import os
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


_initialized = False


def setup_dynatrace_tracing(service_name: str = "ui-fraud-coordination-agent") -> None:
    """Initialize Dynatrace tracing.

    Safe to call multiple times — only the first call takes effect.

    Args:
        service_name: How this service appears in Dynatrace traces.
    """
    global _initialized
    if _initialized:
        return

    tenant_url = os.environ.get("DYNATRACE_TENANT_URL")
    api_token = os.environ.get("DYNATRACE_API_TOKEN")

    if not tenant_url or not api_token:
        print("Dynatrace tracing skipped: DYNATRACE_TENANT_URL or DYNATRACE_API_TOKEN not set")
        return

    # Lazy imports — OTel packages are heavy
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    # Dynatrace's OTLP endpoint follows a specific URL pattern
    otlp_endpoint = f"{tenant_url.rstrip('/')}/api/v2/otlp/v1/traces"

    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        headers={"Authorization": f"Api-Token {api_token}"},
    )

    # Don't replace Arize's existing tracer provider — get whatever's there and
    # add Dynatrace as an additional span processor.
    existing_provider = trace.get_tracer_provider()
    if isinstance(existing_provider, TracerProvider):
        provider = existing_provider
    else:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

    provider.add_span_processor(BatchSpanProcessor(exporter))

    # Auto-instrument pymongo and requests
    PymongoInstrumentor().instrument()
    RequestsInstrumentor().instrument()

    _initialized = True
    print(f"Dynatrace tracing initialized for service: {service_name}")


def get_tracer(name: str = __name__):
    """Get a tracer for creating custom spans."""
    from opentelemetry import trace
    return trace.get_tracer(name)