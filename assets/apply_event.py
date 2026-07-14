# -*- coding: utf-8 -*-
"""Turn an issue title into a disaster (or wipe the slate clean).

Called by .github/workflows/disaster.yml:
    python assets/apply_event.py "<issue title>" "<issue number>"

The issue number becomes the event's seed, so two people pressing the same button never get
the same damage — and the whole map stays reproducible from state.json alone.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "state.json")
README_PATH = os.path.join(os.path.dirname(HERE), "README.md")

# the headlines carry emoji; on a cp1252 console printing them would raise and fail the job
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

KINDS = {
    "flood": "🌊 Thuỷ triều dâng — nước tràn vào từ mép thành phố",
    "earthquake": "🌍 Động đất — nhà sập rải rác, mặt đường nứt toác",
    "lightning": "⚡ Sấm sét — vài căn trúng sét, cháy đen còn bốc khói",
    "war": "🚀 Tên lửa — hố bom, và cả khu phố quanh điểm rơi bị san phẳng",
    "reset": "♻️ Xây lại từ đầu — thành phố nguyên vẹn như chưa từng có gì xảy ra",
}


def main():
    title = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    kind = title.split("disaster:", 1)[1].strip() if "disaster:" in title else ""
    if kind not in KINDS:
        print(f"ignored=true")
        return 0

    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8-sig") as f:
            state = json.load(f)
    else:
        state = {"events": []}

    if kind == "reset":
        state["events"] = []
    else:
        state.setdefault("events", []).append({"kind": kind, "seed": seed})

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # Bump the ?v= on the banner. Without this the reader keeps seeing the OLD map: GitHub and
    # the browser both cache raw.githubusercontent.com for minutes, and the URL never changed.
    version = state.get("version", 0) + 1
    state["version"] = version
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if os.path.exists(README_PATH):
        with open(README_PATH, encoding="utf-8") as f:
            readme = f.read()
        readme = re.sub(r"(assets/saigon\.svg)(\?v=\d+)?", rf"\1?v={version}", readme, count=1)
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(readme)

    # hand these back to the workflow so it can reply on the issue
    print(f"ignored=false")
    print(f"kind={kind}")
    print(f"headline={KINDS[kind]}")
    print(f"total={len(state['events'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
