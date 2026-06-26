#!/bin/bash
# 发送 Telegram 通知 — 合并信号+纸面交易, 去重同 bar
set -euo pipefail

SIGNAL_FILE="${1:-signal_output.txt}"
PAPER_FILE="${2:-paper_output.txt}"
SENT_LOG="${3:-/tmp/telegram_sent_bar.txt}"

# 提取 TELEGRAM 块
SIGNAL_MSG=$(awk '/---TELEGRAM---/{flag=1; next} flag' "$SIGNAL_FILE" 2>/dev/null || echo "信号: 获取失败")
PAPER_MSG=$(awk '/---TELEGRAM---/{flag=1; next} flag' "$PAPER_FILE" 2>/dev/null || echo "纸面: 获取失败")

# 提取 bar 时间做去重 key
BAR_TIME=$(echo "$SIGNAL_MSG" | grep -oP '20\d\d-\d\d-\d\d \d\d:\d\d' | head -1)
if [ -n "$BAR_TIME" ] && [ -f "$SENT_LOG" ]; then
    if grep -qF "$BAR_TIME" "$SENT_LOG" 2>/dev/null; then
        echo "⏭ 跳过: bar $BAR_TIME 已发送过" >&2
        exit 0
    fi
fi

MSG="[ETH 4h] $(date -u '+%H:%M %Z')

${SIGNAL_MSG}

${PAPER_MSG}"

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" \
  -d text="${MSG}" > /dev/null

# 记录已发送 bar
if [ -n "$BAR_TIME" ]; then
    echo "$BAR_TIME $(date -u +%s)" >> "$SENT_LOG"
fi
