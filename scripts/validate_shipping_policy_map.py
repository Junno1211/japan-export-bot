#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump_shipping_policies.py の TSV を入力に、config の SHIPPING_POLICY_MAP と突き合わせる。

policy 表示名 → USD band の解析は shipping_policy_select.parse_band_from_policy_name に従う
（README / test_rules と同じ命名: $X–$Y または $X-$Y、カンマ可。policy_label_for_bracket と対応）。

終了コード: ERROR が 1 件でもあれば非0。WARNING のみなら 0。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config  # noqa: E402
from shipping_policy_select import (  # noqa: E402
    bracket_key_to_band_bounds,
    iter_required_bracket_keys,
    parse_band_from_policy_name,
)


def _read_tsv_rows(path: str | None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if path:
        with open(path, encoding="utf-8") as fp:
            lines = fp.readlines()
    else:
        lines = sys.stdin.readlines()
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            print(f"WARNING: skip non-TSV line (need id<TAB>name): {line[:80]!r}", file=sys.stderr)
            continue
        pid, name = parts[0].strip(), parts[1].strip()
        if pid and name:
            rows.append((pid, name))
    return rows


def _band_matches_bracket(lo: float, hi: float, bracket_key: int) -> bool:
    elo, ehi = bracket_key_to_band_bounds(bracket_key)
    return abs(lo - elo) < 0.02 and abs(hi - ehi) < 0.02


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate SHIPPING_POLICY_MAP against dump TSV.")
    ap.add_argument(
        "tsv_file",
        nargs="?",
        default=None,
        help="dump_shipping_policies.py 出力ファイル（省略時は stdin）",
    )
    args = ap.parse_args()

    rows = _read_tsv_rows(args.tsv_file)
    id_to_name: dict[str, str] = {}
    for pid, name in rows:
        id_to_name[pid] = name

    cap = float(config.LISTING_MAX_PRICE_USD)
    req_keys = iter_required_bracket_keys(cap)

    errors: list[str] = []
    warnings: list[str] = []

    key_to_pid: dict[int, str] = {}
    for k in req_keys:
        raw = config.SHIPPING_POLICY_MAP.get(k)
        if raw is None:
            errors.append(f"ERROR: bracket_key={k} missing from SHIPPING_POLICY_MAP")
            continue
        pid = str(raw).strip()
        if not pid:
            lo, hi = bracket_key_to_band_bounds(k)
            errors.append(
                f"ERROR: bracket_key={k} (${lo:g}–${hi:g}) has empty Profile ID in map"
            )
            continue
        if not pid.isdigit():
            errors.append(f"ERROR: bracket_key={k} non-numeric profile id {pid!r}")
            continue
        key_to_pid[k] = pid
        if pid not in id_to_name:
            errors.append(
                f"ERROR: bracket_key={k} maps to profile_id={pid} not present in TSV dump"
            )
            continue
        pname = id_to_name[pid]
        try:
            lo, hi = parse_band_from_policy_name(pname)
        except ValueError as ex:
            warnings.append(
                f"WARNING: bracket_key={k} profile_id={pid} name={pname!r} — {ex}"
            )
            continue
        if not _band_matches_bracket(lo, hi, k):
            elo, ehi = bracket_key_to_band_bounds(k)
            errors.append(
                f"ERROR: bracket_key={k} expects band ~${elo:g}–${ehi:g} but "
                f"policy name {pname!r} parses to ${lo:g}–${hi:g}"
            )

    pid_to_keys: dict[str, list[int]] = defaultdict(list)
    for k, pid in key_to_pid.items():
        pid_to_keys[pid].append(k)
    for pid, ks in sorted(pid_to_keys.items(), key=lambda x: x[0]):
        if len(ks) > 1:
            ks_sorted = sorted(ks)
            errors.append(
                f"ERROR: profile_id={pid} shared by bracket_keys={ks_sorted} "
                "(本命運用では band ごとに別 Profile ID を推奨)"
            )

    used_ids = set(key_to_pid.values())
    dump_ids = set(id_to_name.keys())
    orphans = dump_ids - used_ids
    for oid in sorted(orphans):
        warnings.append(
            f"WARNING: TSV profile_id={oid} name={id_to_name[oid]!r} "
            "not referenced by any required bracket_key in current map"
        )

    print("=== WARNING ===")
    for w in warnings:
        print(w)
    if not warnings:
        print("(none)")
    print("=== ERROR ===")
    for e in errors:
        print(e)
    if not errors:
        print("(none)")

    if errors:
        print(
            f"=== RESULT: FAIL — {len(errors)} ERROR(s), {len(warnings)} WARNING(s) ===",
        )
        return 1
    print(f"=== RESULT: OK — 0 ERROR, {len(warnings)} WARNING(s) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
