"""Physical AI - Experiment 6: train a 2-4-1 network on XOR.

Hidden layer: ReLU.
Output layer: linear. Classification uses a fixed threshold of 0.5
(class 1 if y >= 0.5 else class 0). That rule is defined here, before
any physical comparison, so it is not chosen after seeing SPICE results.

A sigmoid output is unnecessary for this 4-point dataset and would add
an analog nonlinearity that Experiments 4-5 did not validate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "xor_model.npz"

SEED = 42
HIDDEN = 4
LR = 0.05
BETA1 = 0.9
BETA2 = 0.999
ADAM_EPS = 1e-8
MAX_EPOCHS = 8000
MAX_ATTEMPTS = 25
CLASS_THRESHOLD = 0.5  # fixed before physical comparison

X = np.array(
    [
        [0.0, 0.0],
        [0.0, 1.0],
        [1.0, 0.0],
        [1.0, 1.0],
    ]
)
Y = np.array([[0.0], [1.0], [1.0], [0.0]])


def relu(z: np.ndarray) -> np.ndarray:
    return np.maximum(0.0, z)


def classify(output: np.ndarray) -> np.ndarray:
    return (output >= CLASS_THRESHOLD).astype(int)


def forward(
    x: np.ndarray, w1: np.ndarray, b1: np.ndarray, w2: np.ndarray, b2: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    z1 = x @ w1.T + b1
    h = relu(z1)
    y = h @ w2.T + b2
    return z1, h, y


def loss_mse(y_hat: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((y_hat - y) ** 2))


def _adam_state(*arrays: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(np.zeros_like(a), np.zeros_like(a)) for a in arrays]


def _adam_step(
    param: np.ndarray,
    grad: np.ndarray,
    state: tuple[np.ndarray, np.ndarray],
    step: int,
) -> np.ndarray:
    m, v = state
    m *= BETA1
    m += (1.0 - BETA1) * grad
    v *= BETA2
    v += (1.0 - BETA2) * (grad * grad)
    m_hat = m / (1.0 - BETA1**step)
    v_hat = v / (1.0 - BETA2**step)
    param -= LR * m_hat / (np.sqrt(v_hat) + ADAM_EPS)
    return param


def _init_params(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    w1 = rng.normal(0.0, np.sqrt(2.0 / 2), size=(HIDDEN, 2))
    b1 = rng.normal(0.0, 0.1, size=(HIDDEN,))
    w2 = rng.normal(0.0, np.sqrt(2.0 / HIDDEN), size=(1, HIDDEN))
    b2 = rng.normal(0.0, 0.1, size=(1,))
    return w1, b1, w2, b2


def _run_attempt(
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, float, float]:
    w1, b1, w2, b2 = _init_params(rng)
    s_w1, s_b1, s_w2, s_b2 = _adam_state(w1, b1, w2, b2)
    epoch = 0
    for epoch in range(1, MAX_EPOCHS + 1):
        z1, h, y_hat = forward(X, w1, b1, w2, b2)
        n = X.shape[0]
        dy = 2.0 * (y_hat - Y) / n
        dw2 = dy.T @ h
        db2 = dy.sum(axis=0)
        dh = dy @ w2
        dz1 = dh * (z1 > 0)
        dw1 = dz1.T @ X
        db1 = dz1.sum(axis=0)
        w1 = _adam_step(w1, dw1, s_w1, epoch)
        b1 = _adam_step(b1, db1, s_b1, epoch)
        w2 = _adam_step(w2, dw2, s_w2, epoch)
        b2 = _adam_step(b2, db2, s_b2, epoch)
        _, _, y_now = forward(X, w1, b1, w2, b2)
        pred = classify(y_now).reshape(-1)
        target = Y.reshape(-1).astype(int)
        if np.array_equal(pred, target) and loss_mse(y_now, Y) < 1e-4:
            break
    _, _, y_hat = forward(X, w1, b1, w2, b2)
    pred = classify(y_hat).reshape(-1)
    target = Y.reshape(-1).astype(int)
    return w1, b1, w2, b2, epoch, loss_mse(y_hat, Y), float(np.mean(pred == target))


def train() -> dict[str, np.ndarray | float | int | str]:
    rng = np.random.default_rng(SEED)
    best: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, float, float] | None = None
    used_attempt = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = _run_attempt(rng)
        used_attempt = attempt
        if best is None or result[6] > best[6] or (result[6] == best[6] and result[5] < best[5]):
            best = result
        if result[6] >= 1.0 and result[5] < 1e-4:
            break
    assert best is not None
    w1, b1, w2, b2, epoch, final_loss, accuracy = best
    return {
        "W1": w1,
        "b1": b1,
        "W2": w2,
        "b2": b2,
        "architecture": np.array("2-4-1"),
        "seed": np.array(SEED),
        "epochs": np.array(epoch),
        "attempts": np.array(used_attempt),
        "loss": np.array(final_loss),
        "accuracy": np.array(accuracy),
        "class_threshold": np.array(CLASS_THRESHOLD),
        "output_activation": np.array("linear"),
    }


def main() -> int:
    print("PHYSICAL AI - EXPERIMENT 6")
    print("Train XOR (NumPy, no PyTorch/TensorFlow)")
    print()
    print(f"seed: {SEED}")
    print("architecture: 2 -> 4 ReLU -> 1 linear")
    print(f"classification: output >= {CLASS_THRESHOLD} -> class 1, else class 0")
    print()

    model = train()
    w1 = np.asarray(model["W1"])
    b1 = np.asarray(model["b1"])
    w2 = np.asarray(model["W2"])
    b2 = np.asarray(model["b2"])
    _, _, y_hat = forward(X, w1, b1, w2, b2)
    pred = classify(y_hat).reshape(-1)
    target = Y.reshape(-1).astype(int)
    acc = float(model["accuracy"])
    loss = float(model["loss"])
    epochs = int(model["epochs"])

    print(f"{'Input':<10} {'Target':>6} {'Software':>10} {'Class':>6}")
    for x, t, y, c in zip(X, target, y_hat.reshape(-1), pred):
        print(f"{np.array2string(x, separator=', '):<10} {t:6d} {y:10.6f} {c:6d}")
    print()
    print(f"init attempts used: {int(model['attempts'])}")
    print(f"epochs on accepted attempt: {epochs}")
    print(f"final MSE loss: {loss:.6e}")
    print(f"software accuracy: {acc * 100:.0f}%")
    print()
    print("W1")
    print(w1)
    print("b1")
    print(b1)
    print("W2")
    print(w2)
    print("b2")
    print(b2)
    print()

    if acc < 1.0:
        print("TRAINING FAILED")
        print("Software model did not classify all four XOR examples correctly.")
        print("Not saving a model. Hyperparameters may need another run,")
        print("but weights will not be hand-edited.")
        return 1

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(MODEL_PATH, **model)
    print(f"saved frozen model: {MODEL_PATH}")
    print()
    print("TRAINING COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
