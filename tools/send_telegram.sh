#!/bin/bash
# 发送 Telegram 通知
MSG=$(grep -A5 "TELEGRAM" output.txt | head -10)
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" \
  -d text="[ETH 4h] $(date -u '+%H:%M UTC')
${MSG}" > /dev/null
