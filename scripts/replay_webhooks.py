import argparse
import json
import urllib.request
from pathlib import Path


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1] / "webhooks.jsonl"),
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks")
    args = parser.parse_args()

    for line in Path(args.path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        result = post_json(args.url, payload)
        print(f"{payload.get('seq')}: {payload.get('event')} -> {result}")


if __name__ == "__main__":
    main()
