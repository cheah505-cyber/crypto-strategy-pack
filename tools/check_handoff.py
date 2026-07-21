from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_STATES = {"ACTIVE", "PAUSED", "BLOCKED", "COMPLETE", "MONITORING"}
REQUIRED_KEYS = (
    "handoff_version",
    "status",
    "updated_at",
    "work_unit_id",
    "phase",
    "current_file",
    "next_action_file",
    "next_action_anchor",
    "next_action",
    "acceptance",
    "blocked_by",
    "running_processes",
    "external_responsibilities",
    "baseline_revision",
    "last_verified_at",
    "last_verified_command",
)
REQUIRED_HEADINGS = (
    "## 0. 接管状态",
    "## 1. 最后完成",
    "## 2. 精确暂停点",
    "## 3. 当前工作现场",
    "## 4. 下一动作与验收",
    "## 5. 未决与风险",
    "## 6. 最近验证",
    "## 7. 恢复命令",
)


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
        key = key.strip()
        value = value.strip().strip('"')
        if not key or not value:
            raise ValueError(f"元数据键值不能为空：{line}")
        if key in metadata:
            raise ValueError(f"元数据键重复：{key}")
        metadata[key] = value
    return metadata, "\n".join(lines[end + 1 :])


def project_path(relative: str) -> Path | None:
    if relative == "none":
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"路径必须是项目内相对路径：{relative}")
    resolved = (ROOT / candidate).resolve()
    if ROOT.resolve() not in resolved.parents and resolved != ROOT.resolve():
        raise ValueError(f"路径越出项目目录：{relative}")
    return resolved


def validate(allow_dirty: bool = False) -> tuple[list[str], dict[str, str]]:
    errors: list[str] = []
    handoff = ROOT / "HANDOFF.md"
    if not handoff.is_file() or handoff.stat().st_size == 0:
        return ["缺少或为空：HANDOFF.md"], {}
    try:
        metadata, body = parse_frontmatter(handoff.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        return [f"HANDOFF 元数据错误：{exc}"], {}

    for key in REQUIRED_KEYS:
        if key not in metadata:
            errors.append(f"HANDOFF 缺少元数据：{key}")
    if errors:
        return errors, metadata

    state = metadata["status"]
    if metadata["handoff_version"] != "1":
        errors.append(f"不支持的 handoff_version：{metadata['handoff_version']}")
    if state not in ALLOWED_STATES:
        errors.append(f"HANDOFF 状态不合法：{state}")
    if not re.fullmatch(r"[A-Z][A-Z0-9-]{2,31}", metadata["work_unit_id"]):
        errors.append(f"工作单元 ID 格式不合法：{metadata['work_unit_id']}")

    timestamps: dict[str, datetime] = {}
    for key in ("updated_at", "last_verified_at"):
        try:
            timestamps[key] = datetime.fromisoformat(metadata[key])
            if timestamps[key].tzinfo is None:
                errors.append(f"{key} 必须包含时区")
        except ValueError:
            errors.append(f"{key} 不是 ISO 8601 时间：{metadata[key]}")
    if len(timestamps) == 2 and timestamps["last_verified_at"] > timestamps["updated_at"]:
        errors.append("last_verified_at 不能晚于 updated_at")

    for key in ("current_file", "next_action_file"):
        try:
            path = project_path(metadata[key])
            if path is not None and not path.exists():
                errors.append(f"HANDOFF 指向不存在路径：{key}={metadata[key]}")
            if key == "next_action_file" and path and metadata["next_action_anchor"].startswith("#"):
                target = path.read_text(encoding="utf-8-sig", errors="ignore")
                if metadata["next_action_anchor"] not in target:
                    errors.append(f"下一动作锚点不存在：{metadata['next_action_anchor']}")
        except ValueError as exc:
            errors.append(str(exc))

    if state == "ACTIVE" and metadata["current_file"] == "none":
        errors.append("ACTIVE 状态必须填写 current_file")
    if state == "PAUSED":
        if metadata["running_processes"] != "none":
            errors.append("PAUSED 状态不能保留运行进程")
        if metadata["external_responsibilities"] != "none":
            errors.append("PAUSED 状态不能保留外部责任")
    if state == "MONITORING":
        if metadata["running_processes"] == "none" or metadata["external_responsibilities"] == "none":
            errors.append("MONITORING 状态必须声明远端进程和外部责任")
    if state == "BLOCKED" and metadata["blocked_by"] == "none":
        errors.append("BLOCKED 状态必须填写 blocked_by")
    if state != "BLOCKED" and metadata["blocked_by"] != "none":
        errors.append(f"{state} 状态不能声明 blocked_by")
    if state == "COMPLETE" and metadata["current_file"] != "none":
        errors.append("COMPLETE 状态不能保留 current_file")

    for heading in REQUIRED_HEADINGS:
        if heading not in body:
            errors.append(f"HANDOFF 缺少章节：{heading}")
    if f"状态：`{state}`" not in body:
        errors.append("HANDOFF 正文状态与元数据不一致")
    if f"工作单元：`{metadata['work_unit_id']}`" not in body:
        errors.append("HANDOFF 正文工作单元与元数据不一致")

    if not (ROOT / ".git").is_dir():
        errors.append("项目不是独立 Git 仓库")
    elif not allow_dirty and state in {"PAUSED", "MONITORING", "COMPLETE"}:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False
        )
        if status.returncode != 0:
            errors.append("无法读取 Git 工作区状态：" + status.stderr.strip())
        elif status.stdout.strip():
            errors.append(f"{state} 状态要求 Git 工作区清洁")
    return errors, metadata


def print_resume(metadata: dict[str, str]) -> None:
    print("RESUME:")
    print(f"  状态：{metadata['status']}")
    print(f"  工作单元：{metadata['work_unit_id']}")
    print(f"  阶段：{metadata['phase']}")
    print(f"  当前文件：{metadata['current_file']}")
    print(f"  下一位置：{metadata['next_action_file']} -> {metadata['next_action_anchor']}")
    print(f"  下一动作：{metadata['next_action']}")
    print(f"  验收：{metadata['acceptance']}")
    print(f"  阻断：{metadata['blocked_by']}")
    print(f"  外部责任：{metadata['external_responsibilities']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查结构化 Handoff")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    errors, metadata = validate(allow_dirty=args.allow_dirty)
    if errors:
        print("FAIL: Handoff 未闭环")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("PASS: Handoff 结构、语义、路径与 Git 状态完整")
    if args.resume:
        print_resume(metadata)
    return 0


if __name__ == "__main__":
    sys.exit(main())

