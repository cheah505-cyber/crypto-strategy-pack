#!/bin/bash
# 发送 Telegram 通知 — 合并信号+纸面交易, 双去重
# 去重 1: state.json last_telegram_bar (可靠, 不依赖 git push)
# 去重 2: sent_log 文件 (备份, CI runner 内)
set -euo pipefail

SIGNAL_FILE="${1:-signal_output.txt}"
PAPER_FILE="${2:-paper_output.txt}"
SENT_LOG="${3:-/tmp/telegram_sent_bar.txt}"
STATE_FILE="${4:-paper_trade/state.json}"

# 提取 TELEGRAM 块
SIGNAL_MSG=$(awk '/---TELEGRAM---/{flag=1; next} flag' "$SIGNAL_FILE" 2>/dev/null || echo "信号: 获取失败")
PAPER_MSG=$(awk '/---TELEGRAM---/{flag=1; next} flag' "$PAPER_FILE" 2>/dev/null || echo "纸面: 获取失败")

# 提取 bar 时间
BAR_TIME=$(echo "$SIGNAL_MSG" | grep -oP '20\d\d-\d\d-\d\d \d\d:\d\d' | head -1)

# 去重检查 1: state.json (最可靠 — paper_trade 的单一真相源)
if [ -n "$BAR_TIME" ] && [ -f "$STATE_FILE" ]; then
    LAST_SENT=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('last_telegram_bar',''))" 2>/dev/null || echo "")
    if [ "$LAST_SENT" = "$BAR_TIME" ]; then
        echo "⏭ 跳过 (state): bar $BAR_TIME 已发送" >&2
        exit 0
    fi
fi

# 去重检查 2: sent_log 文件
if [ -n "$BAR_TIME" ] && [ -f "$SENT_LOG" ]; then
    if grep -qF "$BAR_TIME" "$SENT_LOG" 2>/dev/null; then
        echo "⏭ 跳过 (log): bar $BAR_TIME 已发送" >&2
        exit 0
    fi
fi

MSG="[ETH 4h] $(date -u '+%H:%M %Z')

${SIGNAL_MSG}

${PAPER_MSG}"

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" \
  -d text="${MSG}" > /dev/null

# 记录到 state.json (可靠持久化) — 必须用绝对路径
if [ -n "$BAR_TIME" ] && [ -f "$STATE_FILE" ]; then
    ABS_STATE=$(realpath "$STATE_FILE" 2>/dev/null || echo "$STATE_FILE")
    python3 -c "
import json, sys
try:
    s = json.load(open('$ABS_STATE'))
    s['last_telegram_bar'] = '$BAR_TIME'
    json.dump(s, open('$ABS_STATE','w'), indent=2)
    print('OK', file=sys.stderr)
except Exception as e:
    print(f'state update failed: {e}', file=sys.stderr)
" 2>&1 || echo "WARN: state.json update failed" >&2
fi

# 记录到 sent_log (备份)
if [ -n "$BAR_TIME" ]; then
    echo "$BAR_TIME $(date -u +%s)" >> "$SENT_LOG"
fi
