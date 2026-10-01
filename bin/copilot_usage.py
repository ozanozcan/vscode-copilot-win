#!/usr/bin/env python3
"""Summarize content-free Copilot Agent Host OTel JSONL usage."""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


USAGE_FIELDS = {
    "gen_ai.usage.input_tokens": "input_tokens",
    "gen_ai.usage.output_tokens": "output_tokens",
    "gen_ai.usage.cache_read.input_tokens": "cache_read_tokens",
    "gen_ai.usage.cache_creation.input_tokens": "cache_write_tokens",
}


def attribute_value(value):
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            return value[key]
    return None


def attributes(span):
    return {
        item["key"]: attribute_value(item.get("value", {}))
        for item in span.get("attributes", [])
        if "key" in item
    }


def otlp_spans(record):
    for resource in record.get("resourceSpans", []):
        for scope in resource.get("scopeSpans", []):
            yield from scope.get("spans", [])


def integer(value):
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def tracker_metadata(tracker_paths):
    sessions = defaultdict(set)
    for path in tracker_paths:
        try:
            tracker = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid tracker {path}: {error}") from error
        stem = tracker.get("stem") if isinstance(tracker.get("stem"), str) else "unknown"
        action = tracker.get("mow_action") if isinstance(tracker.get("mow_action"), str) else "unknown"
        for conversation_id in tracker.get("sessions", []):
            if isinstance(conversation_id, str) and conversation_id:
                sessions[conversation_id].add((action, stem))
    return sessions


def pricing_data(pricing_path):
    if pricing_path is None:
        return {}
    try:
        data = json.loads(pricing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid pricing file {pricing_path}: {error}") from error
    return data if isinstance(data, dict) else {}


def credit_estimate(usage, model, pricing):
    models = pricing.get("models") if isinstance(pricing.get("models"), dict) else {}
    rates = models.get(model)
    credit_usd = pricing.get("credit_usd")
    if not isinstance(rates, dict) or not isinstance(credit_usd, (int, float)) or credit_usd <= 0:
        return {"status": "unknown"}
    rate_fields = {
        "input_tokens": "input_usd_per_million",
        "output_tokens": "output_usd_per_million",
        "cache_read_tokens": "cache_read_usd_per_million",
        "cache_write_tokens": "cache_write_usd_per_million",
    }
    if any(not isinstance(rates.get(rate), (int, float)) or rates[rate] < 0
           for rate in rate_fields.values()):
        return {"status": "unknown"}
    cost_usd = sum(usage[field] * rates[rate] / 1_000_000 for field, rate in rate_fields.items())
    return {"status": "calculated", "credits": cost_usd / credit_usd}


def summarize(otel_path, tracker_paths=(), pricing_path=None):
    totals = defaultdict(lambda: {field: 0 for field in USAGE_FIELDS.values()})
    seen_span_ids = set()
    metadata = tracker_metadata(tracker_paths)
    pricing = pricing_data(pricing_path)
    with otel_path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error.msg}") from error
            for span in otlp_spans(record):
                data = attributes(span)
                if span.get("name") != "invoke_agent" and data.get("gen_ai.operation.name") != "invoke_agent":
                    continue
                conversation_id = data.get("gen_ai.conversation.id")
                if not conversation_id:
                    continue
                span_id = (span.get("traceId"), span.get("spanId"))
                if all(span_id):
                    if span_id in seen_span_ids:
                        continue
                    seen_span_ids.add(span_id)
                key = (
                    str(conversation_id),
                    str(data.get("gen_ai.agent.name") or "unknown"),
                    str(data.get("gen_ai.response.model") or data.get("gen_ai.request.model") or "unknown"),
                )
                for otel_key, report_key in USAGE_FIELDS.items():
                    totals[key][report_key] += integer(data.get(otel_key))

    records = []
    for (conversation_id, agent, model), usage in sorted(totals.items()):
        matches = metadata.get(conversation_id, set())
        action, stem = next(iter(matches)) if len(matches) == 1 else ("unknown", "unknown")
        records.append({
            "conversation_id": conversation_id,
            "agent": agent,
            "model": model,
            **usage,
            "mow_action": action,
            "stem": stem,
            "alias": f"chat {conversation_id} - {action} - {stem}",
            "ai_credit_estimate": credit_estimate(usage, model, pricing),
        })
    return {"records": records}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otel", type=Path, required=True, help="Copilot OTel JSONL export")
    parser.add_argument("--tracker", type=Path, action="append", default=[],
                        help="MOW tracker.json with Copilot conversation IDs in sessions")
    parser.add_argument("--pricing", type=Path,
                        help="published per-model token pricing and the USD value of one AI credit")
    args = parser.parse_args(argv)
    try:
        report = summarize(args.otel, args.tracker, args.pricing)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())