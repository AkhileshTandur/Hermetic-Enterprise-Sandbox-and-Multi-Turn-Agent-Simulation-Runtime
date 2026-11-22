"""Demo redactor: structured secrets and emails; not a comprehensive PII detector."""

import json
import re

SECRET = re.compile(r"(?i)(authorization|password|secret|api.?key|access.?token)")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(x) for x in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(redact(json.loads(value)), sort_keys=True)
            except (ValueError, RecursionError):
                pass
        return EMAIL.sub("[EMAIL]", value)
    return value
