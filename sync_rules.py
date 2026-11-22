#!/usr/bin/env python3

import os
import tempfile
import shutil
import urllib.request
from pathlib import Path
from datetime import datetime

import yaml

# Configuration
TEMPLATE = "Custom_Clash_Full.yaml"

URL = (
    "https://raw.githubusercontent.com/"
    "Aethersailor/Custom_OpenClash_Rules/"
    "main/cfg/yaml/" + TEMPLATE
)

WORK = Path(__file__).resolve().parent
OUTPUT = WORK / "routing.yaml"

# Download upstream template
print(datetime.now().isoformat(timespec="seconds"))
print("Downloading:", URL)

req = urllib.request.Request(
    URL,
    headers={"User-Agent": "3x-ui-rules-sync/1.0"}
)

with urllib.request.urlopen(req, timeout=30) as r:
    raw = r.read(2 * 1024 * 1024 + 1)

if len(raw) > 2 * 1024 * 1024:
    raise ValueError("Upstream file too large")

config = yaml.safe_load(raw)
providers = config["proxy-providers"]

if set(providers) != {"provider1"}:
    raise ValueError("Unexpected provider structure")

# Convert provider-level filter
pattern = providers["provider1"].get("filter", "")

prefix = "^(?!.*("
suffix = ")).*$"

if not (
    pattern.startswith(prefix)
    and pattern.endswith(suffix)
):
    raise ValueError("Unexpected provider filter")

words = pattern[len(prefix):-len(suffix)].split("|")

# Do not mistake GB region codes for traffic quotas
words = [w for w in words if w != "GB"]

exclude_filter = (
    "(" + "|".join(words) + r"|\d+(?:\.\d+)?\s*GB)"
)

# Convert proxy groups
groups = config["proxy-groups"]
converted = 0

for group in groups:
    use = group.pop("use", [])

    if not use:
        continue

    if set(use) != {"provider1"}:
        raise ValueError("Unknown provider reference")

    group["include-all-proxies"] = True

    old = group.get("exclude-filter", "")

    group["exclude-filter"] = (
        "(?:" + old + ")|(?:" + exclude_filter + ")"
        if old else exclude_filter
    )

    group["empty-fallback"] = "REJECT"

    converted += 1

# Generate routing-only configuration
result = {
    "proxy-groups": groups,
    "rule-providers": config["rule-providers"],
    "rules": config["rules"],
}

# Validate group references
names = [g["name"] for g in groups]

if len(names) != len(set(names)):
    raise ValueError("Duplicate proxy group names")

known = set(names) | {
    "DIRECT", "REJECT", "REJECT-DROP",
    "PASS", "GLOBAL", "PROXY"
}

for g in groups:
    for ref in g.get("proxies", []):
        if ref not in known:
            raise ValueError(
                f"Invalid group reference: {ref}"
            )

# Validate rules
for rule in result["rules"]:
    parts = [p.strip() for p in rule.split(",")]

    if len(parts) < 2:
        raise ValueError(f"Invalid rule: {rule}")

    if parts[0] == "RULE-SET":
        if parts[1] not in result["rule-providers"]:
            raise ValueError(f"Unknown rule set: {parts[1]}")

    while parts[-1].lower() in ("no-resolve", "src"):
        parts.pop()

    if parts[-1] not in known:
        raise ValueError(f"Invalid rule target: {parts[-1]}")

if not result["rules"][-1].startswith("MATCH,"):
    raise ValueError("Missing final MATCH rule")

# Generate YAML
content = yaml.safe_dump(
    result,
    allow_unicode=True,
    sort_keys=False,
    width=4096,
    default_flow_style=False
)

WORK.mkdir(parents=True, exist_ok=True)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

(WORK / "upstream.yaml").write_bytes(raw)

# Atomic replacement with backup
if OUTPUT.exists() and OUTPUT.read_text(
    encoding="utf-8"
) == content:
    print("No changes")
else:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=OUTPUT.parent,
        delete=False
    ) as f:
        f.write(content)
        tmp = Path(f.name)

    try:
        tmp.chmod(0o644)

        if OUTPUT.exists():
            shutil.copy2(
                OUTPUT, str(OUTPUT) + ".bak"
            )

        os.replace(tmp, OUTPUT)
    finally:
        tmp.unlink(missing_ok=True)

    print("Updated:", OUTPUT)

print("Converted groups:", converted)
print("Proxy groups:", len(groups))
print("Rule providers:", len(result["rule-providers"]))
print("Rules:", len(result["rules"]))
print("Success")
