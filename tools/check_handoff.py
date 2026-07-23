from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_STATES = {"ACTIVE", "PAUSED", "BLOCKED", "COMPLETE", "MONITORING"}
REQUIRED_KEYS = (
    "handoff_version", "status", "updated_at", "work_unit_id", "phase",
    "owner", "session_id", "active_branch", "started_at", "lease_until",
    "touched_paths", "current_file", "next_action_file", "next_action_anchor",
    "next_action", "acceptance", "blocked_by", "running_processes",
    "external_responsibilities", "work_started_from", "monitoring_provider",
    "monitoring_target", "expected_interval_minutes", "stale_after_minutes",
    "last_verified_at", "last_verified_command",
)
REQUIRED_HEADINGS = tuple(f"## {number}. {title}" for number, title in enumerate((
    "接管状态", "最后完成", "精确暂停点", "当前工作现场", "下一动作与验收",
    "未决与风险", "最近验证", "恢复命令",
)))
MONITORING_POLICY = ".handoff-monitoring.json"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("文件开头缺少 ---")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("Front matter 缺少结束 ---") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"无法解析元数据行：{line}")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip('"')
        if not key or not value:
            raise ValueError(f"元数据键值不能为空：{line}")
        if key in metadata:
            raise ValueError(f"元数据键重复：{key}")
        metadata[key] = value
    return metadata, "\n".join(lines[end + 1 :])


def run_git(root: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    return result.returncode, (result.stdout.strip() or result.stderr.strip())


def parse_sync_counts(value: str) -> tuple[int, int]:
    parts = value.replace("\t", " ").split()
    if len(parts) != 2:
        raise ValueError(f"无法解析 Git ahead/behind：{value}")
    return int(parts[0]), int(parts[1])


def project_path(root: Path, relative: str) -> Path | None:
    if relative == "none":
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"路径必须是项目内相对路径：{relative}")
    resolved, root_resolved = (root / candidate).resolve(), root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise ValueError(f"路径越出项目目录：{relative}")
    return resolved


def parse_time(key: str, value: str, errors: list[str], allow_none: bool = False) -> datetime | None:
    if allow_none and value == "none":
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            errors.append(f"{key} 必须包含时区")
        return parsed
    except ValueError:
        errors.append(f"{key} 不是 ISO 8601 时间：{value}")
        return None


def load_monitoring_policy(root: Path, errors: list[str]) -> dict:
    path = root / MONITORING_POLICY
    if not path.is_file():
        errors.append(f"MONITORING 状态缺少策略文件：{MONITORING_POLICY}")
        return {}
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"无法读取 {MONITORING_POLICY}：{exc}")
        return {}
    if not isinstance(policy, dict) or policy.get("version") != 1:
        errors.append(f"{MONITORING_POLICY} 必须是 version=1 的 JSON 对象")
        return {}
    return policy


def run_monitoring_checks(root: Path, policy: dict, errors: list[str]) -> None:
    checks = policy.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append(f"{MONITORING_POLICY} 必须声明非空 checks")
        return
    for item in checks:
        if not isinstance(item, dict):
            errors.append(f"{MONITORING_POLICY} 的 checks 项必须是对象")
            continue
        name, script, args = item.get("name"), item.get("script"), item.get("args", [])
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{MONITORING_POLICY} 的检查名称不能为空")
            continue
        if not isinstance(script, str) or not script.endswith(".py") or not isinstance(args, list):
            errors.append(f"监控检查 {name} 的 script/args 不合法")
            continue
        try:
            path = project_path(root, script)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if path is None or not path.is_file() or any(not isinstance(arg, str) for arg in args):
            errors.append(f"监控检查 {name} 指向无效脚本或参数：{script}")
            continue
        result = subprocess.run(
            [sys.executable, str(path), *args], cwd=root, text=True,
            capture_output=True, check=False,
        )
        if result.returncode:
            detail = result.stdout.strip() or result.stderr.strip() or f"exit={result.returncode}"
            errors.append(f"监控检查未通过（{name}）：{detail}")


def validate_monitoring_sync(
    root: Path, ahead: int, behind: int, errors: list[str], warnings: list[str]
) -> None:
    initial_error_count = len(errors)
    policy = load_monitoring_policy(root, errors)
    if not policy:
        return
    if ahead:
        errors.append(f"MONITORING 本地存在 {ahead} 个未推送提交")
        return
    max_behind = policy.get("max_behind_commits")
    authors = policy.get("allowed_author_emails")
    subject_pattern = policy.get("subject_pattern")
    allowed_paths = policy.get("allowed_paths")
    if not isinstance(max_behind, int) or max_behind < 0:
        errors.append(f"{MONITORING_POLICY} 的 max_behind_commits 必须是非负整数")
        return
    if not isinstance(authors, list) or not authors or any(not isinstance(x, str) for x in authors):
        errors.append(f"{MONITORING_POLICY} 的 allowed_author_emails 不合法")
        return
    if not isinstance(allowed_paths, list) or not allowed_paths or any(not isinstance(x, str) for x in allowed_paths):
        errors.append(f"{MONITORING_POLICY} 的 allowed_paths 不合法")
        return
    try:
        subject_re = re.compile(subject_pattern)
    except (TypeError, re.error) as exc:
        errors.append(f"{MONITORING_POLICY} 的 subject_pattern 不合法：{exc}")
        return
    if behind > max_behind:
        errors.append(f"MONITORING 远端领先 {behind} 个提交，超过策略上限 {max_behind}")
        return

    code, commits_text = run_git(root, "rev-list", "--reverse", "HEAD..@{upstream}")
    if code:
        errors.append(f"无法枚举 MONITORING 远端提交：{commits_text}")
        return
    commits = [line for line in commits_text.splitlines() if line]
    if len(commits) != behind:
        errors.append(f"MONITORING 提交计数不一致：计数={behind}，枚举={len(commits)}")
        return
    allowed_authors, allowed_path_set = set(authors), set(allowed_paths)
    for commit in commits:
        code, identity = run_git(root, "show", "-s", "--format=%ae%x00%s%x00%P", commit)
        if code:
            errors.append(f"无法读取监控提交 {commit[:12]}：{identity}")
            continue
        parts = identity.split("\x00")
        if len(parts) != 3:
            errors.append(f"监控提交元数据异常：{commit[:12]}")
            continue
        email, subject, parents = parts
        if email not in allowed_authors:
            errors.append(f"监控提交作者不在白名单：{commit[:12]} {email}")
        if not subject_re.fullmatch(subject):
            errors.append(f"监控提交标题不符合策略：{commit[:12]} {subject}")
        if len(parents.split()) != 1:
            errors.append(f"监控提交不允许是合并或根提交：{commit[:12]}")
        code, paths_text = run_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
        if code:
            errors.append(f"无法读取监控提交路径：{commit[:12]} {paths_text}")
            continue
        unexpected = sorted(set(paths_text.splitlines()) - allowed_path_set)
        if unexpected:
            errors.append(f"监控提交修改了非白名单路径：{commit[:12]} {', '.join(unexpected)}")
    if len(errors) == initial_error_count:
        if behind:
            warnings.append(f"MONITORING 受控远端领先 {behind} 个提交，已通过作者、标题和路径白名单")
        run_monitoring_checks(root, policy, errors)


def validate(
    root: Path = ROOT, allow_dirty: bool = False, refresh_remote: bool = False
) -> tuple[list[str], list[str], dict[str, str]]:
    errors: list[str] = []
    warnings: list[str] = []
    handoff = root / "HANDOFF.md"
    if not handoff.is_file() or handoff.stat().st_size == 0:
        return ["缺少或为空：HANDOFF.md"], warnings, {}
    try:
        metadata, body = parse_frontmatter(handoff.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        return [f"HANDOFF 元数据错误：{exc}"], warnings, {}
    for key in REQUIRED_KEYS:
        if key not in metadata:
            errors.append(f"HANDOFF 缺少元数据：{key}")
    if errors:
        return errors, warnings, metadata

    state = metadata["status"]
    if metadata["handoff_version"] != "2":
        errors.append(f"不支持的 handoff_version：{metadata['handoff_version']}")
    if state not in ALLOWED_STATES:
        errors.append(f"HANDOFF 状态不合法：{state}")
    if not re.fullmatch(r"[A-Z][A-Z0-9-]{2,31}", metadata["work_unit_id"]):
        errors.append(f"工作单元 ID 格式不合法：{metadata['work_unit_id']}")

    updated = parse_time("updated_at", metadata["updated_at"], errors)
    verified = parse_time("last_verified_at", metadata["last_verified_at"], errors)
    started = parse_time("started_at", metadata["started_at"], errors, allow_none=True)
    lease = parse_time("lease_until", metadata["lease_until"], errors, allow_none=True)
    if updated and verified and verified > updated:
        errors.append("last_verified_at 不能晚于 updated_at")
    if started and lease and lease <= started:
        errors.append("lease_until 必须晚于 started_at")

    for key in ("current_file", "next_action_file"):
        try:
            path = project_path(root, metadata[key])
            if path is not None and not path.exists():
                errors.append(f"HANDOFF 指向不存在路径：{key}={metadata[key]}")
            if key == "next_action_file" and path and metadata["next_action_anchor"].startswith("#"):
                if metadata["next_action_anchor"] not in path.read_text(encoding="utf-8-sig", errors="ignore"):
                    errors.append(f"下一动作锚点不存在：{metadata['next_action_anchor']}")
        except ValueError as exc:
            errors.append(str(exc))
    for relative in metadata["touched_paths"].split(";"):
        try:
            project_path(root, relative.strip())
        except ValueError as exc:
            errors.append(str(exc))

    inactive = state in {"PAUSED", "COMPLETE"}
    if state == "ACTIVE":
        for key in ("owner", "session_id", "started_at", "lease_until", "touched_paths", "current_file"):
            if metadata[key] == "none":
                errors.append(f"ACTIVE 状态必须填写 {key}")
        if lease and lease <= datetime.now(lease.tzinfo):
            errors.append("ACTIVE 租约已过期，必须续期、暂停或由接管者显式接管")
    if inactive:
        for key in ("owner", "session_id", "started_at", "lease_until", "touched_paths"):
            if metadata[key] != "none":
                errors.append(f"{state} 状态不能保留 {key}")
        if metadata["running_processes"] != "none" or metadata["external_responsibilities"] != "none":
            errors.append(f"{state} 状态不能保留运行进程或外部责任")
    if state == "COMPLETE" and metadata["current_file"] != "none":
        errors.append("COMPLETE 状态不能保留 current_file")
    if state == "BLOCKED" and metadata["blocked_by"] == "none":
        errors.append("BLOCKED 状态必须填写 blocked_by")
    if state != "BLOCKED" and metadata["blocked_by"] != "none":
        errors.append(f"{state} 状态不能声明 blocked_by")
    if state == "MONITORING":
        for key in ("owner", "session_id", "running_processes", "external_responsibilities",
                    "monitoring_provider", "monitoring_target"):
            if metadata[key] == "none":
                errors.append(f"MONITORING 状态必须填写 {key}")
        for key in ("expected_interval_minutes", "stale_after_minutes"):
            if not metadata[key].isdigit() or int(metadata[key]) <= 0:
                errors.append(f"MONITORING 状态要求 {key} 为正整数")
    elif any(metadata[key] != "none" for key in
             ("monitoring_provider", "monitoring_target", "expected_interval_minutes", "stale_after_minutes")):
        errors.append(f"{state} 状态不能保留监控配置")

    for heading in REQUIRED_HEADINGS:
        if heading not in body:
            errors.append(f"HANDOFF 缺少章节：{heading}")
    if f"状态：`{state}`" not in body:
        errors.append("HANDOFF 正文状态与元数据不一致")
    if f"工作单元：`{metadata['work_unit_id']}`" not in body:
        errors.append("HANDOFF 正文工作单元与元数据不一致")

    if not (root / ".git").is_dir():
        errors.append("项目不是独立 Git 仓库")
    else:
        code, branch = run_git(root, "branch", "--show-current")
        if code or branch != metadata["active_branch"]:
            errors.append(f"active_branch 与 Git 当前分支不一致：记录={metadata['active_branch']}，实际={branch}")
        code, _ = run_git(root, "cat-file", "-e", f"{metadata['work_started_from']}^{{commit}}")
        if code:
            errors.append(f"work_started_from 不是有效提交：{metadata['work_started_from']}")
        if not allow_dirty and state in {"PAUSED", "MONITORING", "COMPLETE"}:
            if refresh_remote:
                code, output = run_git(root, "fetch", "origin", "--prune")
                if code:
                    errors.append(f"UNVERIFIED: 无法刷新远端引用：{output}")
            code, status = run_git(root, "status", "--porcelain")
            if code or status:
                errors.append(f"{state} 状态要求 Git 工作区清洁")
            code, upstream = run_git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
            if code:
                errors.append("无法确认上游同步状态")
            else:
                try:
                    ahead, behind = parse_sync_counts(upstream)
                    if state == "MONITORING":
                        validate_monitoring_sync(root, ahead, behind, errors, warnings)
                    elif ahead or behind:
                        errors.append(f"{state} 状态要求与上游同步，当前 ahead/behind={ahead}/{behind}")
                except ValueError as exc:
                    errors.append(str(exc))
        if allow_dirty:
            warnings.append("--allow-dirty 仅供提交前检查，不能作为最终闭环证据")
    return errors, warnings, metadata


def print_resume(root: Path, metadata: dict[str, str]) -> None:
    _, head = run_git(root, "rev-parse", "--short", "HEAD")
    _, sync = run_git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    print("RESUME:")
    for label, key in (("状态", "status"), ("工作单元", "work_unit_id"), ("阶段", "phase"),
                       ("负责人", "owner"), ("会话", "session_id"), ("租约截止", "lease_until"),
                       ("涉及路径", "touched_paths"), ("当前文件", "current_file"),
                       ("下一动作", "next_action"), ("验收", "acceptance"),
                       ("外部责任", "external_responsibilities"), ("更新时间", "updated_at"),
                       ("最后验证", "last_verified_at")):
        print(f"  {label}：{metadata[key]}")
    print(f"  Git：{metadata['active_branch']}@{head}，ahead/behind={sync or 'unknown'}")
    if metadata["status"] == "MONITORING":
        print("  远端健康：未检查；运行项目的 monitoring health checker")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Handoff v2")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--offline", action="store_true", help="不刷新远端；结果不能证明远端闭环")
    args = parser.parse_args()
    errors, warnings, metadata = validate(
        allow_dirty=args.allow_dirty,
        refresh_remote=not args.offline and not args.allow_dirty,
    )
    if args.offline and not args.allow_dirty:
        warnings.append("--offline 未刷新远端引用，只能验证本地结构")
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        print("FAIL: Handoff 未闭环")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("PASS: Handoff v2 结构、占用、路径与 Git 状态完整")
    if args.resume:
        print_resume(ROOT, metadata)
    return 0


if __name__ == "__main__":
    sys.exit(main())
