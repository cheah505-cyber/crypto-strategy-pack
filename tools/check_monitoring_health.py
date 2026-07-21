from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_handoff import ROOT, parse_frontmatter


def gh_command() -> str | None:
    return shutil.which("gh") or next((str(path) for path in (
        Path("/mnt/c/Program Files/GitHub CLI/gh.exe"),
        Path("C:/Program Files/GitHub CLI/gh.exe"),
    ) if path.is_file()), None)


def run_json(command: list[str]) -> object:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "GitHub CLI 调用失败")
    return json.loads(result.stdout)


def evaluate(workflow: dict, runs: list[dict], stale_minutes: int, current: datetime) -> list[str]:
    errors: list[str] = []
    if workflow.get("state") != "active":
        errors.append(f"Signal Check 工作流不是 active：{workflow.get('state', 'unknown')}")
    successes = [run for run in runs if run.get("status") == "completed" and run.get("conclusion") == "success"]
    if not successes:
        errors.append("找不到成功完成的 Signal Check 运行")
        return errors
    latest = max(successes, key=lambda run: run.get("updatedAt", ""))
    completed = datetime.fromisoformat(latest["updatedAt"].replace("Z", "+00:00"))
    age = (current.astimezone(timezone.utc) - completed.astimezone(timezone.utc)).total_seconds() / 60
    if age > stale_minutes:
        errors.append(f"最近成功运行已过期：{age:.0f} 分钟 > {stale_minutes} 分钟")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Crypto GitHub Actions 监控是否存活")
    parser.add_argument("--fixture", type=Path, help="测试用 JSON：workflow + runs")
    args = parser.parse_args()
    metadata, _ = parse_frontmatter((ROOT / "HANDOFF.md").read_text(encoding="utf-8-sig"))
    if metadata.get("status") != "MONITORING":
        print("SKIP: 当前不是 MONITORING 状态")
        return 0
    try:
        stale = int(metadata["stale_after_minutes"])
        if args.fixture:
            payload = json.loads(args.fixture.read_text(encoding="utf-8"))
            workflow, runs = payload["workflow"], payload["runs"]
        else:
            gh = gh_command()
            if not gh:
                print("UNVERIFIED: 找不到 GitHub CLI，无法验证远端监控")
                return 2
            repository = metadata["monitoring_target"].split(":", 1)[0]
            workflow = run_json([gh, "api", f"repos/{repository}/actions/workflows/signal_check.yml"])
            runs_payload = run_json([
                gh, "api", f"repos/{repository}/actions/workflows/signal_check.yml/runs?per_page=20"
            ])
            runs = [
                {"status": run.get("status"), "conclusion": run.get("conclusion"),
                 "createdAt": run.get("created_at"), "updatedAt": run.get("updated_at"),
                 "url": run.get("html_url")}
                for run in runs_payload.get("workflow_runs", [])
            ]
        errors = evaluate(workflow, runs, stale, datetime.now(timezone.utc))
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"UNVERIFIED: 无法验证远端监控：{exc}")
        return 2
    if errors:
        print("FAIL: Crypto 远端监控不健康")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("PASS: Signal Check 已启用，且最近成功运行未超过过期阈值")
    return 0


if __name__ == "__main__":
    sys.exit(main())
