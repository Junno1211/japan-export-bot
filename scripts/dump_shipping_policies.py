#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eBay に登録されている Fulfillment（Shipping）ポリシーを列挙し、TSV で stdout に出す。

認証・環境変数の読み方は Trading 本流と同じく config 経由（auto_lister / ebay_updater と同型）。
使用 API: Sell Account API GET /sell/account/v1/fulfillment_policy
  ※ ユーザーアクセストークンが Account API で受け付けられる必要があります。
  IAF 形式のみで REST が 401 になる場合は、eBay Developer で OAuth（sell.account 等）を再取得し
  利用可能なユーザー向け Bearer を .env に設定してください（値は本章に出さない）。

出力: profile_id<TAB>profile_name（1 行 1 ポリシー）。トークン・秘密は一切出さない。
"""
from __future__ import annotations

import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import EBAY_AUTH_TOKEN, EBAY_ENV  # noqa: E402


def _account_api_origin() -> str:
    if (EBAY_ENV or "").strip().lower() == "sandbox":
        return "https://api.sandbox.ebay.com"
    return "https://api.ebay.com"


def _summarize_ebay_errors(resp: requests.Response) -> None:
    try:
        body = resp.json()
    except Exception:
        print(f"HTTP {resp.status_code}: non-JSON body", file=sys.stderr)
        return
    errs = body.get("errors")
    if isinstance(errs, list):
        for e in errs[:12]:
            if not isinstance(e, dict):
                continue
            eid = e.get("errorId")
            msg = e.get("longMessage") or e.get("message") or e.get("shortMessage")
            print(f"  ebay_error: {eid} {msg}", file=sys.stderr)
    else:
        print(f"HTTP {resp.status_code}: unexpected JSON shape", file=sys.stderr)


def main() -> int:
    token = (EBAY_AUTH_TOKEN or "").strip()
    if not token:
        print("ERROR: EBAY_AUTH_TOKEN is empty (set in .env)", file=sys.stderr)
        return 1

    origin = _account_api_origin()
    url = f"{origin}/sell/account/v1/fulfillment_policy"
    params = {"marketplace_id": "EBAY_US"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=60)
    except requests.RequestException as ex:
        print(f"ERROR: request failed: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1

    if resp.status_code != 200:
        print(f"ERROR: fulfillment_policy list HTTP {resp.status_code}", file=sys.stderr)
        _summarize_ebay_errors(resp)
        if resp.status_code == 401:
            print(
                "HINT: Account API は OAuth ユーザーアクセストークンが必要なことがあります。"
                " Trading の IAF トークンだけでは 401 になる場合があります（eBay ドキュメント参照）。",
                file=sys.stderr,
            )
        return 1

    try:
        data = resp.json()
    except json.JSONDecodeError as ex:
        print(f"ERROR: invalid JSON: {ex}", file=sys.stderr)
        return 1

    policies = data.get("fulfillmentPolicies")
    if not isinstance(policies, list):
        print("ERROR: response missing fulfillmentPolicies array", file=sys.stderr)
        return 1

    rows_out = 0
    for pol in policies:
        if not isinstance(pol, dict):
            continue
        pid = pol.get("fulfillmentPolicyId")
        name = pol.get("name")
        if pid is None or name is None:
            continue
        pid_s = str(pid).strip()
        name_s = str(name).strip()
        if not pid_s or not name_s:
            continue
        sys.stdout.write(f"{pid_s}\t{name_s}\n")
        rows_out += 1

    if rows_out == 0:
        print("ERROR: no policies with fulfillmentPolicyId and name in response", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
