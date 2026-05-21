#!/usr/bin/env bash
# Ralph-style 回测循环 — 每次迭代干净上下文，状态仅靠文件传递
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASKS_FILE="$SCRIPT_DIR/tasks.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.json"
FINDINGS_FILE="$SCRIPT_DIR/findings.md"
RESULTS_DIR="$SCRIPT_DIR/results"
MAX_ITERATIONS="${1:-20}"
CLAUDE_CMD="claude"

# ── 初始化 ──────────────────────────────────────────────
if [ ! -f "$PROGRESS_FILE" ]; then
  echo '[]' > "$PROGRESS_FILE"
fi
if [ ! -f "$FINDINGS_FILE" ]; then
  echo "# 回测发现记录\n\n> 增量追加，每轮回测后的关键发现。\n" > "$FINDINGS_FILE"
fi

# ── 自动归档上次 run ────────────────────────────────────
ARCHIVE_DIR="$SCRIPT_DIR/archive"
if [ -d "$RESULTS_DIR" ] && [ "$(ls -A "$RESULTS_DIR" 2>/dev/null)" ]; then
  ARCHIVE_NAME="$(date +%Y-%m-%d-%H%M)"
  mkdir -p "$ARCHIVE_DIR"
  mv "$RESULTS_DIR" "$ARCHIVE_DIR/$ARCHIVE_NAME"
  echo "📦 上次结果已归档: archive/$ARCHIVE_NAME/"
fi
mkdir -p "$RESULTS_DIR"

echo "============================================"
echo "  Crypto Backtest Loop (Ralph模式)"
echo "  最大迭代: $MAX_ITERATIONS"
echo "  任务文件: $TASKS_FILE"
echo "============================================"
echo ""

# ── 主循环 ──────────────────────────────────────────────
for i in $(seq 1 "$MAX_ITERATIONS"); do
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  迭代 #$i / $MAX_ITERATIONS"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # 找到第一个未完成任务
  TASK=$(python3 -c "
import json, sys
with open('$TASKS_FILE') as f:
    tasks = json.load(f)
pending = [t for t in tasks['tasks'] if not t.get('completed', False)]
if pending:
    t = pending[0]
    print(json.dumps({'id': t['id'], 'name': t['name'], 'factor': t.get('factor',''), 'params': t.get('params',{})}))
else:
    print('ALL_DONE')
")

  if [ "$TASK" = "ALL_DONE" ]; then
    echo ""
    echo "✅ 全部任务完成。退出循环。"
    echo "<promise>COMPLETE</promise>"
    exit 0
  fi

  TASK_ID=$(echo "$TASK" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
  TASK_NAME=$(echo "$TASK" | python3 -c "import json,sys; print(json.load(sys.stdin)['name'])")

  echo "  📋 当前任务: [$TASK_ID] $TASK_NAME"
  echo ""

  # ── 启动全新 Claude 实例 ──────────────────────────────
  START_TIME=$(date +%s)

  OUTPUT=$($CLAUDE_CMD --print <<HEREDOC
$(cat "$SCRIPT_DIR/prompt.md")

## 当前任务

- **任务ID**: $TASK_ID
- **任务名称**: $TASK_NAME
- **因子**: $(echo "$TASK" | python3 -c "import json,sys; print(json.load(sys.stdin)['factor'])")
- **参数**: $(echo "$TASK" | python3 -c "import json,sys; print(json.load(sys.stdin)['params'])")

## 执行步骤

1. 读取 \`$TASKS_FILE\` 和 \`$PROGRESS_FILE\` 了解当前状态
2. 读取 \`$FINDINGS_FILE\` 获取历史发现（如果有）
3. 在 \`$RESULTS_DIR/$TASK_ID/\` 目录下执行回测
4. 回测完成后：
   a. 将完整回测报告写入 \`$RESULTS_DIR/$TASK_ID/report.md\`
   b. 将任务状态更新回 \`$PROGRESS_FILE\`（标记 completed: true，填入结果摘要）
   c. 将关键发现追加到 \`$FINDINGS_FILE\`
   d. 将因子/策略笔记写入 Obsidian vault（如有价值发现）
5. 退出前输出 <promise>DONE</promise> 表示本轮完成
HEREDOC
)

  END_TIME=$(date +%s)
  DURATION=$((END_TIME - START_TIME))

  # ── 检查迭代是否完成 ──────────────────────────────────
  if echo "$OUTPUT" | grep -q "<promise>DONE</promise>"; then
    echo "  ✅ 迭代 #$i 完成 (耗时 ${DURATION}s)"
  else
    echo "  ⚠️  迭代 #$i 结束但未检测到 DONE 信号 (耗时 ${DURATION}s)"
  fi

  echo ""
  sleep 2
done

echo ""
echo "⚠️  达到最大迭代次数 ($MAX_ITERATIONS)，仍有任务未完成。"
echo "   查看: $PROGRESS_FILE"
exit 1
