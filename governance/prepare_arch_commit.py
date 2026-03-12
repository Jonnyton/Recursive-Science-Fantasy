"""
Prepare standardized git metadata for a frontier-gated architecture proposal.

Usage:
  python governance/prepare_arch_commit.py proposals/<proposal>.json
"""

from __future__ import annotations

import json
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python governance/prepare_arch_commit.py proposals/<proposal>.json", file=sys.stderr)
        return 1

    manifest_path = pathlib.Path(sys.argv[1])
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    proposal_id = data["proposal_id"]
    change_kind = data.get("change_kind", "forward_change")
    title = data.get("title", proposal_id)
    rollback_of = data.get("rollback_of", "")
    commit_plan = data.setdefault("commit_plan", {})

    branch_name = commit_plan.get("branch_name") or f"codex/arch-{proposal_id}"
    if change_kind == "rollback":
        target = rollback_of or "previous-architecture-change"
        commit_message = commit_plan.get("commit_message") or f"arch-rollback:{proposal_id}: revert {target}"
    else:
        short_title = title.strip().replace("\n", " ")
        commit_message = commit_plan.get("commit_message") or f"arch:{proposal_id}: {short_title}"

    commit_plan["branch_name"] = branch_name
    commit_plan["commit_message"] = commit_message
    commit_plan.setdefault("isolated_files_only", True)

    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    print(f"proposal_id={proposal_id}")
    print(f"change_kind={change_kind}")
    print(f"branch_name={branch_name}")
    print(f"commit_message={commit_message}")
    print(f"isolated_files_only={commit_plan['isolated_files_only']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
