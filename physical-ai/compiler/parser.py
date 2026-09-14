"""Parse a frozen small MLP from .npz. Does not train or edit weights."""

from __future__ import annotations

from pathlib import Path

import numpy as np

SUPPORTED_HIDDEN = {"relu"}
SUPPORTED_OUTPUT = {"linear", "identity"}


class PhysicalMappingFailed(Exception):
    """The compiler refused to emit an unsafe or unknown physical mapping."""


def load_npz(path: Path) -> dict:
    if not path.is_file():
        raise PhysicalMappingFailed(f"MODEL FILE NOT FOUND: {path}")
    data = np.load(path, allow_pickle=True)
    required = ("W1", "b1", "W2", "b2")
    missing = [k for k in required if k not in data.files]
    if missing:
        raise PhysicalMappingFailed(
            f"UNSUPPORTED MODEL REPRESENTATION: missing {missing}"
        )
    w1 = np.asarray(data["W1"], dtype=float)
    b1 = np.asarray(data["b1"], dtype=float).reshape(-1)
    w2 = np.asarray(data["W2"], dtype=float)
    b2 = np.asarray(data["b2"], dtype=float).reshape(-1)
    if w1.ndim != 2 or w2.ndim != 2:
        raise PhysicalMappingFailed("WEIGHT TENSORS MUST BE 2-D DENSE MATRICES")
    if w1.shape[0] != b1.shape[0]:
        raise PhysicalMappingFailed("W1/b1 SHAPE MISMATCH")
    if w2.shape[0] != b2.shape[0] or w2.shape[1] != w1.shape[0]:
        raise PhysicalMappingFailed("W2/b2/W1 SHAPE MISMATCH")
    hidden = "relu"
    if "hidden_activation" in data.files:
        hidden = str(np.asarray(data["hidden_activation"]).reshape(-1)[0]).lower()
    output = "linear"
    if "output_activation" in data.files:
        output = str(np.asarray(data["output_activation"]).reshape(-1)[0]).lower()
    if hidden not in SUPPORTED_HIDDEN:
        raise PhysicalMappingFailed(
            f"UNSUPPORTED ACTIVATION: hidden={hidden!r} "
            f"(supported {sorted(SUPPORTED_HIDDEN)})"
        )
    if output not in SUPPORTED_OUTPUT:
        raise PhysicalMappingFailed(
            f"UNSUPPORTED ACTIVATION: output={output!r} "
            f"(supported {sorted(SUPPORTED_OUTPUT)})"
        )
    threshold = 0.5
    if "class_threshold" in data.files:
        threshold = float(np.asarray(data["class_threshold"]).reshape(-1)[0])
    return {
        "path": str(path),
        "W1": w1,
        "b1": b1,
        "W2": w2,
        "b2": b2,
        "n_in": int(w1.shape[1]),
        "n_hidden": int(w1.shape[0]),
        "n_out": int(w2.shape[0]),
        "hidden_activation": hidden,
        "output_activation": output,
        "class_threshold": threshold,
        "weights_frozen": True,
    }


def software_forward(
    model: dict, x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.atleast_2d(np.asarray(x, dtype=float))
    z1 = x @ model["W1"].T + model["b1"]
    h = np.maximum(0.0, z1)
    y = h @ model["W2"].T + model["b2"]
    return z1, h, y


def range_analysis(model: dict, inputs: np.ndarray) -> dict:
    z1, h, y = software_forward(model, inputs)
    return {
        "n_vectors": int(np.atleast_2d(inputs).shape[0]),
        "z1_min": float(z1.min()),
        "z1_max": float(z1.max()),
        "h_min": float(h.min()),
        "h_max": float(h.max()),
        "y_min": float(y.min()),
        "y_max": float(y.max()),
        "abs_signal_max": float(
            max(abs(z1).max(), abs(h).max(), abs(y).max(), abs(np.asarray(inputs)).max())
        ),
    }
