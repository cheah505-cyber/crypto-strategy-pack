from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from check_handoff import ROOT, parse_frontmatter, print_resume, validate


def now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git 命令失败")
    return result.stdout.strip()


def read() -> tuple[dict[str, str], str]:
    return parse_frontmatter((ROOT / "HANDOFF.md").read_text(encoding="utf-8-sig"))


def atomic_write(content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".HANDOFF.", suffix=".tmp", dir=ROOT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, ROOT / "HANDOFF.md")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write(metadata: dict[str, str], body: str) -> None:
    body_lines = body.splitlines()
    for index, line in enumerate(body_lines):
        if line.startswith("- 状态：`"):
            body_lines[index] = f"- 状态：`{metadata['status']}`"
        elif line.startswith("- 工作单元：`"):
            body_lines[index] = f"- 工作单元：`{metadata['work_unit_id']}`"
    content = "---\n" + "\n".join(f'{key}: "{value}"' for key, value in metadata.items())
    content += "\n---\n" + "\n".join(body_lines).rstrip() + "\n"
    atomic_write(content)


def ensure_valid(metadata: dict[str, str], body: str) -> None:
    original = (ROOT / "HANDOFF.md").read_text(encoding="utf-8-sig")
    write(metadata, body)
    errors, warnings, _ = validate(allow_dirty=True)
    if errors:
        atomic_write(original)
        raise RuntimeError("更新后的 Handoff 无效：\n  - " + "\n  - ".join(errors))
    for warning in warnings:
        print(f"WARN: {warning}")


def start(args: argparse.Namespace) -> None:
    metadata, body = read()
    current = now()
    if metadata["status"] == "ACTIVE" and metadata["session_id"] != args.session:
        lease = datetime.fromisoformat(metadata["lease_until"])
        if lease > current:
            raise RuntimeError(
                f"工作单元仍由 {metadata['owner']}/{metadata['session_id']} 占用至 {metadata['lease_until']}"
            )
    metadata.update({
        "status": "ACTIVE", "updated_at": current.isoformat(), "owner": args.owner,
        "session_id": args.session, "active_branch": git("branch", "--show-current"),
        "started_at": current.isoformat(),
        "lease_until": (current + timedelta(minutes=args.lease_minutes)).isoformat(),
        "touched_paths": args.paths, "current_file": args.file, "blocked_by": "none",
        "running_processes": "none", "external_responsibilities": "none",
        "work_started_from": git("rev-parse", "HEAD"), "monitoring_provider": "none",
        "monitoring_target": "none", "expected_interval_minutes": "none",
        "stale_after_minutes": "none", "last_verified_at": current.isoformat(),
        "last_verified_command": "python tools/handoff.py start",
    })
    ensure_valid(metadata, body)
    print(f"PASS: 已开始 {metadata['work_unit_id']}，租约至 {metadata['lease_until']}")


def stop(args: argparse.Namespace, state: str) -> None:
    metadata, body = read()
    current = now()
    metadata.update({
        "status": state, "updated_at": current.isoformat(), "owner": "none", "session_id": "none",
        "started_at": "none", "lease_until": "none", "touched_paths": "none",
        "blocked_by": "none", "running_processes": "none", "external_responsibilities": "none",
        "monitoring_provider": "none", "monitoring_target": "none",
        "expected_interval_minutes": "none", "stale_after_minutes": "none",
        "last_verified_at": current.isoformat(), "last_verified_command": f"python tools/handoff.py {args.command}",
    })
    if state == "COMPLETE":
        metadata["current_file"] = "none"
    for key in ("next_file", "anchor", "action", "acceptance"):
        value = getattr(args, key, None)
        if value:
            metadata[{"next_file": "next_action_file", "anchor": "next_action_anchor",
                      "action": "next_action", "acceptance": "acceptance"}[key]] = value
    ensure_valid(metadata, body)
    print(f"PASS: 已将 {metadata['work_unit_id']} 标记为 {state}")
    print("NEXT: 提交并推送 HANDOFF.md 后，再运行严格检查完成闭环")


def block(args: argparse.Namespace) -> None:
    metadata, body = read()
    current = now()
    metadata.update({"status": "BLOCKED", "blocked_by": args.reason,
                     "updated_at": current.isoformat(), "last_verified_at": current.isoformat(),
                     "last_verified_command": "python tools/handoff.py block"})
    ensure_valid(metadata, body)
    print(f"PASS: 已记录阻断：{args.reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Handoff v2 生命周期工具（不自动提交或推送）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    sub.add_parser("verify")
    active = sub.add_parser("start")
    active.add_argument("--owner", required=True)
    active.add_argument("--session", required=True)
    active.add_argument("--file", required=True)
    active.add_argument("--paths", required=True, help="分号分隔的项目内相对路径")
    active.add_argument("--lease-minutes", type=int, default=120)
    for command in ("pause", "complete"):
        target = sub.add_parser(command)
        target.add_argument("--next-file")
        target.add_argument("--anchor")
        target.add_argument("--action")
        target.add_argument("--acceptance")
    blocked = sub.add_parser("block")
    blocked.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        if args.command == "show":
            print_resume(ROOT, read()[0])
        elif args.command == "verify":
            errors, warnings, _ = validate()
            for warning in warnings:
                print(f"WARN: {warning}")
            if errors:
                raise RuntimeError("\n  - ".join(errors))
            print("PASS: Handoff v2 严格闭环")
        elif args.command == "start":
            if args.lease_minutes <= 0:
                raise RuntimeError("lease-minutes 必须为正整数")
            start(args)
        elif args.command == "block":
            block(args)
        else:
            stop(args, "PAUSED" if args.command == "pause" else "COMPLETE")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
