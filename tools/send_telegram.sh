#!/bin/bash
# 发送 Telegram 通知 — 合并信号+纸面交易
set -euo pipefail

SIGNAL_FILE="${1:-signal_output.txt}"
PAPER_FILE="${2:-paper_output.txt}"

# 提取 TELEGRAM 块（---TELEGRAM--- 之后的所有行）
SIGNAL_MSG=$(awk '/---TELEGRAM---/{flag=1; next} flag' "$SIGNAL_FILE" 2>/dev/null || echo "信号: 获取失败")
PAPER_MSG=$(awk '/---TELEGRAM---/{flag=1; next} flag' "$PAPER_FILE" 2>/dev/null || echo "纸面: 获取失败")

MSG="[ETH 4h] $(date -u '+%H:%M %Z')

${SIGNAL_MSG}

${PAPER_MSG}"

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" \
  -d text="${MSG}" > /dev/null
