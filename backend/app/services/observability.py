"""Production observability for tracing, metrics, and analytics snapshots."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Iterator

from app.config import get_settings

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
except Exception:  # pragma: no cover - optional in lightweight test envs
    trace = None  # type: ignore
    Status = None  # type: ignore
    StatusCode = None  # type: ignore

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
except Exception:  # pragma: no cover - optional in lightweight test envs
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    Counter = Gauge = Histogram = None  # type: ignore
    generate_latest = None  # type: ignore


SERVICE_NAME = "codepilot-ai"


def _new_counter(name: str, description: str, labels: list[str] | None = None):
    if Counter is None:
        return None
    try:
        return Counter(name, description, labels or [])
    except ValueError:
        return None


def _new_histogram(name: str, description: str, labels: list[str] | None = None):
    if Histogram is None:
        return None
    try:
        return Histogram(name, description, labels or [])
    except ValueError:
        return None


def _new_gauge(name: str, description: str, labels: list[str] | None = None):
    if Gauge is None:
        return None
    try:
        return Gauge(name, description, labels or [])
    except ValueError:
        return None


HTTP_REQUESTS = _new_counter("codepilot_http_requests_total", "HTTP requests by endpoint.", ["method", "path", "status"])
HTTP_LATENCY = _new_histogram("codepilot_http_request_duration_seconds", "HTTP request latency.", ["method", "path"])
AGENT_LATENCY = _new_histogram("codepilot_agent_execution_duration_seconds", "LangGraph node execution latency.", ["node"])
RETRIEVAL_LATENCY = _new_histogram("codepilot_retrieval_duration_seconds", "Retrieval latency.", ["stage"])
EMBEDDING_LATENCY = _new_histogram("codepilot_embedding_duration_seconds", "Embedding latency.", ["provider", "operation"])
LLM_LATENCY = _new_histogram("codepilot_llm_duration_seconds", "LLM latency.", ["provider", "operation"])
QDRANT_LATENCY = _new_histogram("codepilot_qdrant_query_duration_seconds", "Qdrant query latency.", ["operation"])
TOKEN_USAGE = _new_counter("codepilot_llm_tokens_total", "LLM tokens used.", ["provider", "operation"])
COST_USD = _new_counter("codepilot_llm_cost_usd_total", "Estimated LLM cost in USD.", ["provider", "operation"])
CACHE_REQUESTS = _new_counter("codepilot_cache_requests_total", "Cache requests by result.", ["cache", "result"])
CACHE_HIT_RATIO = _new_gauge("codepilot_cache_hit_ratio", "Cache hit ratio.", ["cache"])


@dataclass
class _LatencyStats:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0

    def to_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "total_ms": round(self.total_ms, 3),
            "avg_ms": round(self.avg_ms, 3),
            "max_ms": round(self.max_ms, 3),
        }


@dataclass
class MetricsStore:
    started_at: float = field(default_factory=time.time)
    lock: Lock = field(default_factory=Lock)
    http_requests: int = 0
    http_errors: int = 0
    agent_execution_time: dict[str, _LatencyStats] = field(default_factory=dict)
    retrieval_latency: dict[str, _LatencyStats] = field(default_factory=dict)
    embedding_latency: dict[str, _LatencyStats] = field(default_factory=dict)
    llm_latency: dict[str, _LatencyStats] = field(default_factory=dict)
    qdrant_query_latency: dict[str, _LatencyStats] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)
    cost_per_request: list[float] = field(default_factory=list)
    cache: dict[str, dict[str, int]] = field(default_factory=dict)

    def record_latency(self, bucket: str, key: str, duration_ms: float) -> None:
        with self.lock:
            target: dict[str, _LatencyStats] = getattr(self, bucket)
            stats = target.setdefault(key, _LatencyStats())
            stats.count += 1
            stats.total_ms += duration_ms
            stats.max_ms = max(stats.max_ms, duration_ms)

    def record_http(self, status_code: int, duration_ms: float) -> None:
        with self.lock:
            self.http_requests += 1
            if status_code >= 500:
                self.http_errors += 1
            stats = self.retrieval_latency.setdefault("api_total", _LatencyStats())
            stats.count += 1
            stats.total_ms += duration_ms
            stats.max_ms = max(stats.max_ms, duration_ms)

    def record_tokens(self, provider: str, operation: str, tokens: int) -> None:
        if tokens <= 0:
            return
        with self.lock:
            key = f"{provider}.{operation}"
            self.token_usage[key] = self.token_usage.get(key, 0) + tokens

    def record_cost(self, cost_usd: float) -> None:
        if cost_usd <= 0:
            return
        with self.lock:
            self.cost_per_request.append(cost_usd)
            if len(self.cost_per_request) > 1000:
                self.cost_per_request = self.cost_per_request[-1000:]

    def record_cache(self, cache_name: str, hit: bool) -> None:
        with self.lock:
            stats = self.cache.setdefault(cache_name, {"hits": 0, "misses": 0})
            stats["hits" if hit else "misses"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            cache = {
                name: {
                    "hits": values["hits"],
                    "misses": values["misses"],
                    "requests": values["hits"] + values["misses"],
                    "hit_ratio": round(values["hits"] / (values["hits"] + values["misses"]), 4)
                    if values["hits"] + values["misses"]
                    else 0.0,
                }
                for name, values in self.cache.items()
            }
            costs = list(self.cost_per_request)
            return {
                "service": SERVICE_NAME,
                "uptime_seconds": int(time.time() - self.started_at),
                "http": {
                    "requests": self.http_requests,
                    "errors": self.http_errors,
                    "error_ratio": round(self.http_errors / self.http_requests, 4) if self.http_requests else 0.0,
                },
                "agent_execution_time": {k: v.to_dict() for k, v in self.agent_execution_time.items()},
                "retrieval_latency": {k: v.to_dict() for k, v in self.retrieval_latency.items()},
                "embedding_latency": {k: v.to_dict() for k, v in self.embedding_latency.items()},
                "llm_latency": {k: v.to_dict() for k, v in self.llm_latency.items()},
                "token_usage": dict(self.token_usage),
                "cost_per_request": {
                    "count": len(costs),
                    "total_usd": round(sum(costs), 6),
                    "avg_usd": round(sum(costs) / len(costs), 6) if costs else 0.0,
                    "last_usd": round(costs[-1], 6) if costs else 0.0,
                },
                "cache_hit_ratio": cache,
                "qdrant_query_latency": {k: v.to_dict() for k, v in self.qdrant_query_latency.items()},
            }


metrics_store = MetricsStore()


def setup_observability() -> None:
    settings = get_settings()

    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

    if settings.otel_exporter_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint))
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: F401
    except Exception:
        pass


def instrument_fastapi(app: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        return


def get_tracer(name: str):
    if trace is None:
        return None
    return trace.get_tracer(name)


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[Any]:
    tracer = get_tracer(__name__)
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, str(value))
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            if Status is not None and StatusCode is not None:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def record_agent_execution(node: str, duration_ms: float) -> None:
    metrics_store.record_latency("agent_execution_time", node, duration_ms)
    if AGENT_LATENCY is not None:
        AGENT_LATENCY.labels(node=node).observe(duration_ms / 1000.0)


def record_retrieval(stage: str, duration_ms: float) -> None:
    metrics_store.record_latency("retrieval_latency", stage, duration_ms)
    if RETRIEVAL_LATENCY is not None:
        RETRIEVAL_LATENCY.labels(stage=stage).observe(duration_ms / 1000.0)


def record_embedding(provider: str, operation: str, duration_ms: float) -> None:
    key = f"{provider}.{operation}"
    metrics_store.record_latency("embedding_latency", key, duration_ms)
    if EMBEDDING_LATENCY is not None:
        EMBEDDING_LATENCY.labels(provider=provider, operation=operation).observe(duration_ms / 1000.0)


def record_llm(provider: str, operation: str, duration_ms: float, tokens: int = 0) -> float:
    key = f"{provider}.{operation}"
    metrics_store.record_latency("llm_latency", key, duration_ms)
    metrics_store.record_tokens(provider, operation, tokens)
    cost_usd = estimate_llm_cost(tokens, provider)
    metrics_store.record_cost(cost_usd)
    if LLM_LATENCY is not None:
        LLM_LATENCY.labels(provider=provider, operation=operation).observe(duration_ms / 1000.0)
    if TOKEN_USAGE is not None and tokens > 0:
        TOKEN_USAGE.labels(provider=provider, operation=operation).inc(tokens)
    if COST_USD is not None and cost_usd > 0:
        COST_USD.labels(provider=provider, operation=operation).inc(cost_usd)
    return cost_usd


def record_qdrant(operation: str, duration_ms: float) -> None:
    metrics_store.record_latency("qdrant_query_latency", operation, duration_ms)
    if QDRANT_LATENCY is not None:
        QDRANT_LATENCY.labels(operation=operation).observe(duration_ms / 1000.0)


def record_cache(cache_name: str, hit: bool) -> None:
    metrics_store.record_cache(cache_name, hit)
    if CACHE_REQUESTS is not None:
        CACHE_REQUESTS.labels(cache=cache_name, result="hit" if hit else "miss").inc()
    stats = metrics_store.snapshot()["cache_hit_ratio"].get(cache_name)
    if CACHE_HIT_RATIO is not None and stats:
        CACHE_HIT_RATIO.labels(cache=cache_name).set(stats["hit_ratio"])


def record_http_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    metrics_store.record_http(status_code, duration_ms)
    if HTTP_REQUESTS is not None:
        HTTP_REQUESTS.labels(method=method, path=path, status=str(status_code)).inc()
    if HTTP_LATENCY is not None:
        HTTP_LATENCY.labels(method=method, path=path).observe(duration_ms / 1000.0)


def extract_token_usage(response: Any) -> int:
    for attr in ("token_usage", "usage", "usage_metadata"):
        usage = getattr(response, attr, None)
        if isinstance(usage, int):
            return usage
        if isinstance(usage, dict):
            total = usage.get("total_tokens") or usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            if total:
                return int(total)
    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(token_usage, dict):
            total = token_usage.get("total_tokens") or token_usage.get("prompt_tokens", 0) + token_usage.get("completion_tokens", 0)
            if total:
                return int(total)
    return 0


async def measured_llm_ainvoke(llm: Any, messages: list[Any], operation: str = "chat") -> tuple[Any, int, int, float]:
    provider = get_settings().llm_provider.value
    with trace_span("llm.ainvoke", provider=provider, operation=operation):
        start = time.perf_counter()
        response = await llm.ainvoke(messages)
        duration_ms = int((time.perf_counter() - start) * 1000)
    tokens = extract_token_usage(response)
    cost_usd = record_llm(provider, operation, duration_ms, tokens)
    return response, duration_ms, tokens, cost_usd


def estimate_llm_cost(tokens: int, provider: str) -> float:
    if tokens <= 0:
        return 0.0
    per_1k = {
        "openai": 0.005,
        "anthropic": 0.008,
        "gemini": 0.001,
        "deepseek": 0.0005,
        "ollama": 0.0,
    }.get(provider, 0.0)
    return (tokens / 1000.0) * per_1k


def system_metrics() -> dict[str, Any]:
    return metrics_store.snapshot()


def prometheus_metrics() -> tuple[bytes, str]:
    if generate_latest is None:
        return b"", CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST
