"""Binance Testnet 测试脚本 — 验证 API 连接和下单流程。

用法:
  1. 打开 https://testnet.binance.vision/
  2. 用 GitHub 登录
  3. 左上角 HMAC → 生成 API Key
  4. 把 Key/Secret 填入下面
  5. 运行本脚本
"""
from __future__ import annotations

import ccxt
import pandas as pd

# 填入你的测试网 API Key
TESTNET_API_KEY = ""
TESTNET_SECRET = ""

if not TESTNET_API_KEY:
    print("=" * 60)
    print("  请先设置 API Key")
    print("=" * 60)
    print()
    print("  1. 打开 https://testnet.binance.vision/")
    print("  2. 右上角 GitHub 登录")
    print("  3. 左侧菜单 → HMAC → 生成 API Key")
    print("  4. 复制 Key 和 Secret 到本文件顶部")
    print()
    exit()

# 测试网配置
exchange = ccxt.binance({
    "apiKey": TESTNET_API_KEY,
    "secret": TESTNET_SECRET,
    "options": {"defaultType": "future"},  # U本位合约
    "urls": {
        "api": {
            "public": "https://testnet.binancefuture.com/fapi/v1",
            "private": "https://testnet.binancefuture.com/fapi/v1",
        },
    },
    "enableRateLimit": True,
})

print("1. 连接测试网...")
try:
    exchange.load_markets()
    print("   ✅ 连接成功")
except Exception as e:
    print(f"   ❌ 连接失败: {e}")
    exit()

print(f"\n2. 余额查询:")
try:
    balance = exchange.fetch_balance()
    total_usdt = balance["USDT"]["total"] if "USDT" in balance else 0
    free_usdt = balance["USDT"]["free"] if "USDT" in balance else 0
    print(f"   USDT 总额: {total_usdt:.2f}")
    print(f"   USDT 可用: {free_usdt:.2f}")
except Exception as e:
    print(f"   ❌ 失败: {e}")

print(f"\n3. ETH/USDT:USDT 市场信息:")
try:
    market = exchange.market("ETH/USDT:USDT")
    print(f"   最小下单: {market['limits']['amount']['min']} ETH")
    print(f"   最小金额: {market['limits']['cost']['min']} USDT" if market['limits']['cost'] else "   最小金额: N/A")
    print(f"   精度: {market['precision']['amount']} ETH")
except Exception as e:
    print(f"   ❌ 失败: {e}")

print(f"\n4. 当前 ETH 价格:")
try:
    ticker = exchange.fetch_ticker("ETH/USDT:USDT")
    print(f"   {ticker['last']:.2f} USDT")
except Exception as e:
    print(f"   ❌ 失败: {e}")

print(f"\n5. 测试下单 (市价买入 0.01 ETH):")
try:
    order = exchange.create_market_buy_order("ETH/USDT:USDT", 0.01)
    print(f"   ✅ 订单已成交: ID = {order['id']}")
    print(f"   成交价: {order['price']:.2f}" if order['price'] else "   成交价: 市价成交")
except Exception as e:
    print(f"   ❌ 下单失败: {e}")

print(f"\n6. 查询持仓:")
try:
    positions = exchange.fetch_positions(["ETH/USDT:USDT"])
    for p in positions:
        if float(p["contracts"]) > 0:
            print(f"   {p['symbol']}: {p['contracts']} 张, 未实现盈亏 {p['unrealizedPnl']}")
except Exception as e:
    print(f"   ❌ 失败: {e}")

print(f"\n7. 平仓测试:")
try:
    exchange.create_market_sell_order("ETH/USDT:USDT", 0.01)
    print("   ✅ 平仓完成")
except Exception as e:
    print(f"   ❌ 平仓失败: {e}")

print(f"\n{'='*60}")
print(f"  测试完成！测试网跑通后就可以切到主网。")
print(f"{'='*60}")
print()
print(f"  切到主网只需:")
print(f"    exchange = ccxt.binance({{")
print(f"        'apiKey': '你的主网KEY',")
print(f"        'secret': '你的主网SECRET',")
print(f"        'options': {{'defaultType': 'future'}},")
print(f"    }})")
