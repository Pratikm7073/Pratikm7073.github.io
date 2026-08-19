"""Penalised least squares, shared by the feature and model layers.

Kept in its own module because both the structural-break test in
`features.py` and the forecasting models in `models.py` need it, and
having either import the other would be circular.
"""

from __future__ import annotations

import numpy as np

__all__ = ["ridge_gcv"]


def ridge_gcv(X: np.ndarray, y: np.ndarray, lambdas) -> tuple[np.ndarray, float]:
    """Ridge with the penalty chosen by generalised cross-validation.

    Two details that are easy to get wrong and expensive to get wrong:

    * **Standardise before penalising.** One lambda has to mean the same
      thing to a 0/1 event dummy and to a trend measured in years.
      Penalising raw columns silently makes the strength of the penalty a
      function of the units.
    * **Never penalise the intercept.** The constant column is dropped
      from the penalised system entirely and recovered afterwards from
      the centred fit; shrinking it towards zero would just bias the
      level of the whole forecast downwards.

    GCV needs the effective degrees of freedom, the trace of the hat
    matrix. That is computed as `trace((Z'Z + lambda*I)^-1 Z'Z)`, a k x k
    operation, rather than by forming the n x n hat matrix itself - same
    number, but k is about twenty-five here and n runs to a thousand.
    """
    n = X.shape[0]
    scale = X.std(axis=0)
    is_const = scale < 1e-12
    keep = ~is_const

    Z = X[:, keep]
    centre = Z.mean(axis=0)
    scale = Z.std(axis=0)
    scale[scale < 1e-12] = 1.0
    Z = (Z - centre) / scale

    y_mean = float(y.mean())
    yc = y - y_mean
    ZtZ = Z.T @ Z
    Zty = Z.T @ yc
    eye = np.eye(Z.shape[1])

    best_gcv, best_b, best_lam = np.inf, None, lambdas[0]
    for lam in lambdas:
        try:
            inv = np.linalg.inv(ZtZ + lam * eye)
        except np.linalg.LinAlgError:
            continue
        b = inv @ Zty
        dof = float(np.trace(inv @ ZtZ)) + 1.0   # +1 for the intercept
        resid = yc - Z @ b
        denom = (1.0 - dof / n) ** 2
        if denom <= 1e-9:
            continue
        gcv = float((resid @ resid) / n / denom)
        if gcv < best_gcv:
            best_gcv, best_b, best_lam = gcv, b, lam

    if best_b is None:
        best_b = np.linalg.lstsq(Z, yc, rcond=None)[0]

    # Map the standardised solution back into the original column space.
    beta = np.zeros(X.shape[1])
    beta[keep] = best_b / scale
    if is_const.any():
        beta[np.argmax(is_const)] = y_mean - float((centre / scale) @ best_b)
    return beta, best_lam


