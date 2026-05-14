"""A fake CLI used by tests.

Emits a few stream-json-like events and exits.
Run directly:  python -m tests.mock_cli <prompt>
"""

import json
import sys
import time


def main(argv):
    prompt = argv[1] if len(argv) > 1 else ""
    events = [
        {"type": "stream_event", "event": {"delta": {"type": "thinking_delta", "thinking": "thinking about: " + prompt[:32]}}},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "Hello, "}}},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "world!"}}},
        {"type": "result", "stop_reason": "end_turn"},
    ]
    for e in events:
        print(json.dumps(e), flush=True)
        time.sleep(0.01)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
