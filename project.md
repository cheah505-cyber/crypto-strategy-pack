# crypto-strategy-pack 项目约定

## 环境
- 系统：Windows
- venv: `.venv`
- python: `.\.venv\Scripts\python.exe`
- 数据目录: `.\data\`

## 路径
- 数据源: `.\data\`（OHLCV CSV）
- 回测代码: `.\backtests\`
- 策略代码: `.\strategies\`

## 纪律
- OHLCV 数据只读，不手动修改
- 回测结果写入 results/ 目录
