"""Emit Experiment 24 summary plots from recorded SPICE metrics."""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compile_xor import PROJECT_ROOT
from test_iv_architectures import ERROR_LIMIT

RESULTS = PROJECT_ROOT / "results"

FMAP = [
    (1e4, 1e-6, 4.8006e-03, 1.0), (1e4, 3e-6, 4.7929e-03, 1.0), (1e4, 1e-5, 4.7725e-03, 1.0),
    (1e4, 2.2e-5, 4.7602e-03, 1.0), (1e4, 3e-5, 4.7676e-03, 1.0), (1e4, 1e-4, 5.4075e-03, 1.0),
    (1e4, 2.14e-4, 8.2105e-03, 1.0),
    (3e4, 1e-6, 1.6059e-03, 1.0), (3e4, 3e-6, 1.5998e-03, 1.0), (3e4, 1e-5, 1.5973e-03, 1.0),
    (3e4, 2.2e-5, 1.6622e-03, 1.0), (3e4, 3e-5, 1.7577e-03, 1.0), (3e4, 1e-4, 3.6371e-03, 1.0),
    (3e4, 2.14e-4, 7.4605e-03, 1.0),
    (5e4, 1e-6, 9.6314e-04, 1.0), (5e4, 3e-6, 9.5871e-04, 1.0), (5e4, 1e-5, 9.7356e-04, 1.0),
    (5e4, 2.2e-5, 1.1239e-03, 1.0), (5e4, 3e-5, 1.3040e-03, 1.0), (5e4, 1e-4, 3.5150e-03, 1.0),
    (5e4, 2.14e-4, 7.4009e-03, 1.0),
    (1e5, 1e-6, 4.8059e-04, 1.0), (1e5, 3e-6, 4.8005e-04, 1.0), (1e5, 1e-5, 5.4402e-04, 1.0),
    (1e5, 2.2e-5, 8.4272e-04, 1.0), (1e5, 3e-5, 1.0925e-03, 1.0), (1e5, 1e-4, 3.4627e-03, 1.0),
    (1e5, 2.14e-4, 7.3713e-03, 1.0),
    (3e5, 1e-6, 1.6010e-04, 1.0), (3e5, 3e-6, 1.7614e-04, 1.0), (3e5, 1e-5, 3.6428e-04, 1.0),
    (3e5, 2.2e-5, 7.6761e-04, 1.0), (3e5, 3e-5, 1.0406e-03, 1.0), (3e5, 1e-4, 3.4427e-03, 1.0),
    (3e5, 2.14e-4, 7.3605e-03, 1.0),
    (1e6, 1e-6, 5.4435e-05, 1.0), (1e6, 3e-6, 1.0930e-04, 1.0), (1e6, 1e-5, 3.4643e-04, 1.0),
    (1e6, 2.2e-5, 7.5804e-04, 1.0), (1e6, 3e-5, 1.0329e-03, 1.0), (1e6, 1e-4, 3.4398e-03, 1.0),
    (1e6, 2.14e-4, 7.3581e-03, 1.0),
]

F_BARS = [
    ("I dump", 3.6069e-15),
    ("L Vos=0", 4.8383e-04),
    ("L 8.75 uV", 5.2453e-04),
    ("L 22 uV", 8.4272e-04),
    ("L 214 uV", 7.3721e-03),
    ("OPA1656", 1.7131e-02),
    ("AZ Vin-only 214 uV", 8.1060e-03),  # Network A; F skipped
    ("AZ-Vref 214 uV", 4.8384e-04),
    ("chopper A 214 uV", 5.7814e-03),
    ("servo 214 uV", 7.3755e-09),
    ("L 0.5% R", 4.1540e-03),
    ("servo 0.5% R", 4.1326e-03),
]


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    gains = sorted({r[0] for r in FMAP})
    vos = sorted({r[1] for r in FMAP})
    mae = np.full((len(vos), len(gains)), np.nan)
    acc = np.full((len(vos), len(gains)), np.nan)
    gi = {g: i for i, g in enumerate(gains)}
    vi = {v: i for i, v in enumerate(vos)}
    for a, v, m, c in FMAP:
        mae[vi[v], gi[a]] = m
        acc[vi[v], gi[a]] = c

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.1))
    im0 = axes[0].imshow(
        np.log10(np.clip(mae, 1e-5, 1e-1)),
        origin="lower",
        aspect="auto",
        extent=[np.log10(gains[0]), np.log10(gains[-1]), np.log10(vos[0]), np.log10(vos[-1])],
    )
    axes[0].set_xlabel("log10 open-loop A")
    axes[0].set_ylabel("log10 |Vos| (V)")
    axes[0].set_title("Network F analog MAE (log10)")
    fig.colorbar(im0, ax=axes[0], fraction=0.046)
    im1 = axes[1].imshow(
        acc,
        origin="lower",
        aspect="auto",
        vmin=0.9,
        vmax=1.0,
        extent=[np.log10(gains[0]), np.log10(gains[-1]), np.log10(vos[0]), np.log10(vos[-1])],
    )
    axes[1].set_xlabel("log10 open-loop A")
    axes[1].set_ylabel("log10 |Vos| (V)")
    axes[1].set_title("Network F classification")
    fig.colorbar(im1, ax=axes[1], fraction=0.046)
    fig.tight_layout()
    p0 = RESULTS / "offset_vg_feasibility_map.png"
    fig.savefig(p0, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    xs = np.arange(len(F_BARS))
    ax.bar(xs, [v for _, v in F_BARS], color="#4c6")
    ax.axhline(ERROR_LIMIT, color="k", ls="--", lw=0.8, label="analog MAE=1e-3")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([k for k, _ in F_BARS], rotation=40, ha="right")
    ax.set_yscale("log")
    ax.set_ylabel("analog MAE")
    ax.set_title("Experiment 24: analog MAE (F unless noted)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p1 = RESULTS / "offset_vg_network_F.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)
    print("wrote", p0)
    print("wrote", p1)


if __name__ == "__main__":
    main()
