"""LightGBM: predict ADX regime change in next 24h (6 bars).

Target: 1 if ADX crosses between trend/range within next 6 bars, else 0.
Features: RSI, ATR%, volume_ratio, close/SMA ratio + lags.
Evaluation: time-series walk-forward (no shuffle).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "eth_usdt_4h.csv"

# Strategy constants (post-optimization baseline)
ADX_PERIOD, ADX_TREND, ADX_RANGE = 14, 30, 15
RSI_PERIOD = 14

# Target window
TARGET_HORIZON = 6  # 6 bars = 24h

N_SPLITS = 5


def load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    df = df.sort_index()
    return df


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute features and ADX regime labels."""
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    # ── ADX ──
    delta = c.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    df["rsi"] = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, np.nan))

    tr1, tr2, tr3 = h - l, (h - c.shift()).abs(), (l - c.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    up, down = h - h.shift(), l.shift() - l
    pdm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    pdi = 100 * (pdm.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean() / atr.replace(0, np.nan))
    ndi = 100 * (ndm.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean() / atr.replace(0, np.nan))
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    df["atr"] = atr
    df["atr_pct"] = atr / c * 100  # ATR as % of price

    # ADX regime
    df["is_trend"] = (df["adx"] > ADX_TREND).astype(int)
    df["is_range"] = (df["adx"] < ADX_RANGE).astype(int)

    # ── Features ──
    df["volume_ratio"] = v / v.rolling(20).mean()  # relative volume
    df["close_sma_ratio"] = c / c.rolling(20).mean()  # price vs SMA20

    # Feature lags (shift to prevent lookahead)
    for col in ["rsi", "atr_pct", "volume_ratio", "close_sma_ratio"]:
        for lag in [1, 2, 3]:
            df[f"{col}_lag{lag}"] = df[col].shift(lag)

    # ADX change features
    df["adx_delta"] = df["adx"].diff()
    df["adx_delta_lag1"] = df["adx_delta"].shift(1)

    # ── Target: regime change in next TARGET_HORIZON bars ──
    regime = df["is_trend"].astype(int)  # 1=trend, 0=not trend (range or neutral)
    # A regime change is when is_trend value changes
    df["regime_change_1h"] = regime.diff().abs().shift(-1)  # next bar
    # Any change in next 6 bars
    df["target"] = (
        regime.diff().abs().rolling(window=TARGET_HORIZON, min_periods=1)
        .max().shift(-TARGET_HORIZON)
    )

    return df


def prepare_ml_data(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Split into feature matrix X and target y, drop NaN rows."""
    feature_cols = [
        "rsi_lag1", "rsi_lag2", "rsi_lag3",
        "atr_pct_lag1", "atr_pct_lag2", "atr_pct_lag3",
        "volume_ratio_lag1", "volume_ratio_lag2", "volume_ratio_lag3",
        "close_sma_ratio_lag1", "close_sma_ratio_lag2", "close_sma_ratio_lag3",
        "adx_delta_lag1",
    ]
    df = df.dropna(subset=feature_cols + ["target"])
    # Also drop rows where adx is still warming up (first ADX_PERIOD*2 bars)
    df = df.iloc[ADX_PERIOD * 2:]
    X = df[feature_cols].copy()
    y = df["target"].astype(int)
    return X, y


def ts_cv_split(X: pd.DataFrame, y: pd.Series, n_splits: int):
    """Time-series aware CV splits — each fold's train ends before test starts."""
    n = len(X)
    fold_size = n // (n_splits + 1)
    for i in range(n_splits):
        train_end = (i + 1) * fold_size
        test_end = train_end + fold_size
        train_idx = list(range(0, train_end))
        test_idx = list(range(train_end, min(test_end, n)))
        yield train_idx, test_idx


def main() -> int:
    import lightgbm as lgb
    from sklearn.metrics import (accuracy_score, classification_report,
                                 confusion_matrix, f1_score, precision_score,
                                 recall_score, roc_auc_score)

    logger.info("Loading data...")
    df = load_data(DATA_PATH)
    logger.info(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    df = compute_features(df)
    X, y = prepare_ml_data(df)

    # Class balance
    pos_ratio = y.mean() * 100
    logger.info(f"Feature matrix: {X.shape}, target pos ratio: {pos_ratio:.1f}%")

    # Walk-forward CV
    n_splits = min(N_SPLITS, len(X) // 500)  # ensure min fold size
    fold_results: list[dict] = []
    feature_importances: list[np.ndarray] = []

    for fold, (train_idx, test_idx) in enumerate(ts_cv_split(X, y, n_splits)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        # Handle class imbalance with scale_pos_weight
        scale_pos = (len(y_train) - y_train.sum()) / y_train.sum()

        model = lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            scale_pos_weight=scale_pos,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], eval_metric="auc")

        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1]

        fold_results.append({
            "fold": fold,
            "train_range": f"{X_train.index[0].date()} → {X_train.index[-1].date()}",
            "test_range": f"{X_test.index[0].date()} → {X_test.index[-1].date()}",
            "n_train": len(X_train),
            "n_test": len(X_test),
            "test_pos_ratio": float(y_test.mean()) * 100,
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "roc_auc": float(roc_auc_score(y_test, y_prob)),
        })
        feature_importances.append(model.feature_importances_)

        logger.info(
            f"Fold {fold}: AUC={fold_results[-1]['roc_auc']:.3f} "
            f"Acc={fold_results[-1]['accuracy']:.3f} "
            f"Prec={fold_results[-1]['precision']:.3f} "
            f"Rec={fold_results[-1]['recall']:.3f}"
        )

    # ── Aggregate ──
    avg_imp = np.mean(feature_importances, axis=0)
    imp_df = pd.DataFrame({"feature": X.columns, "importance": avg_imp}).sort_values("importance", ascending=False)

    print("\n" + "=" * 70)
    print("LightGBM ADX Regime Change Prediction — Walk-Forward Results")
    print("=" * 70)
    print(f"\n  Target: regime change in next {TARGET_HORIZON} bars (24h)")
    print(f"  Data: {X.index[0].date()} → {X.index[-1].date()} ({len(X)} samples)")
    print(f"  Overall pos ratio: {y.mean()*100:.1f}%")
    print(f"  Folds: {n_splits}")
    print()

    for fr in fold_results:
        print(f"  Fold {fr['fold']}:")
        print(f"    Train: {fr['train_range']} ({fr['n_train']} samples)")
        print(f"    Test:  {fr['test_range']} ({fr['n_test']} samples, pos={fr['test_pos_ratio']:.0f}%)")
        print(f"    AUC={fr['roc_auc']:.3f} Acc={fr['accuracy']:.3f} Prec={fr['precision']:.3f} Rec={fr['recall']:.3f} F1={fr['f1']:.3f}")
        print()

    avg_auc = np.mean([r["roc_auc"] for r in fold_results])
    avg_acc = np.mean([r["accuracy"] for r in fold_results])
    avg_f1 = np.mean([r["f1"] for r in fold_results])
    print(f"  Average: AUC={avg_auc:.3f} Acc={avg_acc:.3f} F1={avg_f1:.3f}")
    print()

    # Feature importance
    print(f"  Feature Importance (avg over {n_splits} folds):")
    for _, row in imp_df.iterrows():
        bar = "█" * int(row["importance"] / imp_df["importance"].max() * 30)
        print(f"    {row['feature']:25s} {row['importance']:>8.1f}  {bar}")

    print()

    # ── Strategy Integration Check ──
    print(f"  Strategy Integration Check:")
    print(f"    " + ("-" * 50))
    if avg_auc > 0.65:
        print(f"    [OK] AUC={avg_auc:.3f} > 0.65 — model has predictive power")
        print(f"    Can be used as confirm filter: trade only when model predicts NO regime change")
    else:
        print(f"    [WARN] AUC={avg_auc:.3f} < 0.65 — weak predictive power")
        print(f"    Not suitable as standalone filter")

    if avg_precision := np.mean([r["precision"] for r in fold_results]) > 0.35:
        print(f"    [OK] Precision={avg_precision:.3f} > 0.35 — regime changes are detectable")
    else:
        print(f"    [WARN] Precision={avg_precision:.3f} < 0.35 — too many false positives")

    print(f"\n  Simple baseline: always predict 0 → accuracy = {(1 - y.mean()):.3f}")
    print(f"  Model improvement: +{(avg_acc - (1 - y.mean()))*100:.1f} pp over baseline")
    print()

    # ── Confusion Matrix (last fold) ──
    print(f"  Last Fold Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(f"    TN={cm[0,0]:5d}  FP={cm[0,1]:3d}")
    print(f"    FN={cm[1,0]:3d}  TP={cm[1,1]:5d}")
    print()

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
