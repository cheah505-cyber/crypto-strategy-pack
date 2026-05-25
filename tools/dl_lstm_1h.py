"""LSTM 1h OHLCV — 尝试用深度学习捕获序列模式。

设计：
  - 输入: 48 根 1h K 线 (OHLCV + 衍生特征)
  - 目标: 预测未来 6h 收益方向 (正/负)
  - 模型: 2 层 LSTM + Dropout (防过拟合)
  - 对比: Logistic Regression (看 LSTM 是否超越线性)
  - 验证: 时间序列 Walk-Forward
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "eth_usdt_1h.csv"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

SEQ_LEN = 48        # 2 天 1h 数据
PRED_HORIZON = 6    # 预测未来 6h
BATCH_SIZE = 256
EPOCHS = 50
LR = 0.001


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """构建特征矩阵：原始 OHLCV + 衍生因子。"""
    d = df.copy()
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]

    # 收益率
    for p in [1, 3, 6, 12, 24]:
        d[f"ret_{p}"] = c.pct_change(p)

    # 波动率
    d["range"] = (h - l) / c
    d["range_ma"] = d["range"].rolling(12).mean()

    # 成交量
    d["vol_ma"] = v.rolling(12).mean()
    d["vol_ratio"] = v / d["vol_ma"].replace(0, np.nan)

    # 价格位置
    d["hh_12"] = h.rolling(12).max()
    d["ll_12"] = l.rolling(12).min()
    d["pos_12"] = (c - d["ll_12"]) / (d["hh_12"] - d["ll_12"]).replace(0, 0.5)

    # OHLC 归一化 (除以 close 的滚动均值)
    d["close_norm"] = c / c.rolling(48).mean()
    d["high_norm"] = h / c.rolling(48).mean()
    d["low_norm"] = l / c.rolling(48).mean()
    d["open_norm"] = d["open"] / c.rolling(48).mean()
    d["volume_norm"] = v / v.rolling(48).mean().replace(0, 1)

    return d


def create_sequences(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """创建 (序列, 标签) 对。标签: 未来 PRED_HORIZON 根收益 > 0?"""
    feature_cols = ["close_norm", "high_norm", "low_norm", "open_norm", "volume_norm",
                    "ret_1", "ret_3", "ret_6", "ret_12",
                    "range", "range_ma", "vol_ratio", "pos_12"]

    data = df[feature_cols].values
    future_ret = df["close"].pct_change(PRED_HORIZON).shift(-PRED_HORIZON).values

    X, y = [], []
    for i in range(len(data) - SEQ_LEN - PRED_HORIZON):
        if np.any(np.isnan(data[i : i + SEQ_LEN])) or np.isnan(future_ret[i + SEQ_LEN]):
            continue
        X.append(data[i : i + SEQ_LEN])
        y.append(1 if future_ret[i + SEQ_LEN] > 0 else 0)

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


class LSTMModel(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 64):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers=2,
                            dropout=0.3, batch_first=True)
        self.dropout = nn.Dropout(0.3)
        self.linear = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.dropout(out[:, -1, :])
        return self.linear(out).squeeze()


def train_lstm(X_train, y_train, X_val, y_val) -> LSTMModel:
    model = LSTMModel(X_train.shape[2]).to(DEVICE)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.Adam(model.parameters(), lr=LR)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5)

    train_t = torch.tensor(X_train).to(DEVICE)
    train_l = torch.tensor(y_train).to(DEVICE)
    val_t = torch.tensor(X_val).to(DEVICE)
    val_l = torch.tensor(y_val).to(DEVICE)

    best_val_loss = float("inf")
    best_state = None

    for epoch in range(EPOCHS):
        model.train()
        perm = torch.randperm(len(train_t))
        total_loss = 0
        for i in range(0, len(train_t), BATCH_SIZE):
            idx = perm[i : i + BATCH_SIZE]
            out = model(train_t[idx])
            loss = criterion(out, train_l[idx])
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item()

        model.eval()
        with torch.no_grad():
            val_out = model(val_t)
            val_loss = criterion(val_out, val_l).item()

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = model.state_dict()

    model.load_state_dict(best_state)
    return model


def evaluate(model, X, y) -> dict:
    model.eval()
    with torch.no_grad():
        t = torch.tensor(X).to(DEVICE)
        logits = model(t).cpu().numpy()
        probs = 1 / (1 + np.exp(-logits))
        preds = (probs > 0.5).astype(int)

    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

    return {
        "accuracy": round(float(accuracy_score(y, preds)), 4),
        "f1": round(float(f1_score(y, preds, zero_division=0)), 4),
        "precision": round(float(precision_score(y, preds, zero_division=0)), 4),
        "recall": round(float(recall_score(y, preds, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y, probs)), 4),
        "pos_ratio": round(float(y.mean()) * 100, 1),
        "n": len(y),
    }


def train_logistic(X_train, y_train, X_val, y_val):
    """Logistic Regression 作为线性基线。"""
    from sklearn.linear_model import LogisticRegression
    # 展平序列
    X_train_f = X_train.reshape(X_train.shape[0], -1)
    X_val_f = X_val.reshape(X_val.shape[0], -1)
    model = LogisticRegression(max_iter=1000, C=0.1, penalty="l2")
    model.fit(X_train_f, y_train)
    preds = model.predict(X_val_f)
    probs = model.predict_proba(X_val_f)[:, 1]
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
    return {
        "accuracy": round(float(accuracy_score(y_val, preds)), 4),
        "f1": round(float(f1_score(y_val, preds, zero_division=0)), 4),
        "precision": round(float(precision_score(y_val, preds, zero_division=0)), 4),
        "recall": round(float(recall_score(y_val, preds, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_val, probs)), 4),
    }


# ── 主流程 ──
print("=" * 70)
print("  1h LSTM — 预测未来6h收益方向")
print("=" * 70)

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
if df.index.tz is not None: df.index = df.index.tz_localize(None)
print(f"  Data: {df.index[0]} → {df.index[-1]} ({len(df)} bars)")

df = build_features(df).dropna()
X, y = create_sequences(df)
print(f"  Sequences: {len(X)} (seq_len={SEQ_LEN}, horizon={PRED_HORIZON})")
print(f"  Label balance: up={y.mean()*100:.1f}% down={(1-y.mean())*100:.1f}%")
print(f"  Device: {DEVICE}")
print()

# 时序分割 (前 60% 训练, 20% 验证, 20% 测试)
n = len(X)
train_end = int(n * 0.6)
val_end = int(n * 0.8)

X_train, y_train = X[:train_end], y[:train_end]
X_val, y_val = X[train_end:val_end], y[train_end:val_end]
X_test, y_test = X[val_end:], y[val_end:]

print(f"  Train: {len(X_train)} | Val: {len(X_val)} | Test: {len(X_test)}")
print()

# ── Logistic Regression 基线 ──
print("  Logistic Regression (线性基线):")
lr_metrics = train_logistic(X_train, y_train, X_val, y_val)
print(f"    Test:  Acc={lr_metrics['accuracy']:.3f}  F1={lr_metrics['f1']:.3f}  "
      f"Prec={lr_metrics['precision']:.3f}  Rec={lr_metrics['recall']:.3f}  "
      f"AUC={lr_metrics['roc_auc']:.3f}")
print()

# ── LSTM ──
print("  LSTM (2层, hidden=64, dropout=0.3):")
model = train_lstm(X_train, y_train, X_val, y_val)

for split_name, X_s, y_s in [("Train", X_train, y_train), ("Val", X_val, y_val), ("Test", X_test, y_test)]:
    metrics = evaluate(model, X_s, y_s)
    print(f"    {split_name:>5}: Acc={metrics['accuracy']:.3f}  F1={metrics['f1']:.3f}  "
          f"Prec={metrics['precision']:.3f}  Rec={metrics['recall']:.3f}  "
          f"AUC={metrics['roc_auc']:.3f}  (pos={metrics['pos_ratio']:.0f}% n={metrics['n']})")

print()
print(f"  随机基线: Acc={(1-y_test.mean()):.3f} (always predict majority)")
print()
