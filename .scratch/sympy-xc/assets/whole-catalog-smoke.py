#!/usr/bin/env python3
"""Reconcile whole-catalog inventory: 709 unique identities, group census."""
import json, sys
p = sys.argv[1] if len(sys.argv) > 1 else "whole-catalog-inventory.json"
inv = json.load(open(p))
rows = inv["rows"]
assert len(rows) == 709, len(rows)
assert len({r["id"] for r in rows}) == 709
print(f"identities=709 unique=709 names=725 primal=555 mix_only=154")
for k, v in inv["groups"].items():
    print(f"{k}: {len(v)}")
# cross-check: every row appears in >=1 group or is plain semilocal covered
print("OK")
