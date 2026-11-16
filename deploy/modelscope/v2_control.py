#!/usr/bin/env python3
"""Read-only V2 release checks through the existing local publisher.

No Token/password is accepted or read. Authentication stays in the publisher.
This utility deliberately has no publish, restart or arbitrary request action.
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx


BASE = "http://127.0.0.1:8791"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("local-status", "prepare", "status", "logs", "diagnostics"))
    parser.add_argument("--kind", choices=("build", "run"), default="build")
    args = parser.parse_args()
    try:
        with httpx.Client(trust_env=False, timeout=120, follow_redirects=False) as client:
            homepage = client.get(BASE + "/")
            homepage.raise_for_status()
            if "固定发布至 huawei-pc-agent-app-v2" not in homepage.text:
                raise ValueError("local_publisher_is_not_fixed_v2")
            if args.action == "local-status":
                response = client.get(BASE + "/api/status")
            else:
                csrf = homepage.headers.get("X-CSRF-Token")
                if not csrf:
                    raise ValueError("local_publisher_csrf_unavailable")
                response = client.post(
                    BASE + "/api/actions/" + args.action,
                    headers={"Origin": BASE, "X-CSRF-Token": csrf},
                    json={"kind": args.kind} if args.action == "logs" else {},
                )
            payload = response.json()
            print(json.dumps({"http_status": response.status_code, "result": payload},
                             ensure_ascii=False, indent=2))
            return 0 if response.is_success else 1
    except (httpx.HTTPError, ValueError) as error:
        # Never print request headers, arbitrary response text or local secrets.
        category = str(error) if isinstance(error, ValueError) and str(error).startswith("local_publisher_") else type(error).__name__
        print(json.dumps({"error": category}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
