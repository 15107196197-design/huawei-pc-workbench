"""Container-local liveness check, with no proxy or credentials."""
import json
from urllib.request import ProxyHandler, build_opener


def main() -> None:
    opener = build_opener(ProxyHandler({}))
    with opener.open("http://127.0.0.1:7860/healthz", timeout=4) as response:
        if response.status != 200 or json.loads(response.read(256)) != {"status": "ok"}:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
