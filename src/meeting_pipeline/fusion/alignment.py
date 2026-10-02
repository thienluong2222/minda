"""Word-level sequence alignment and dynamic programming for transcript fusion.

Specification: Section 13.2 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import numpy as np

EPSILON_TOKEN = "<eps>"


def align_word_sequences(
    seq_a: list[str],
    seq_b: list[str],
    match_score: float = 2.0,
    mismatch_penalty: float = -1.0,
    gap_penalty: float = -1.5,
) -> tuple[list[str], list[str]]:
    """Global sequence alignment using Needleman-Wunsch algorithm with epsilon padding."""
    n = len(seq_a)
    m = len(seq_b)

    if n == 0 and m == 0:
        return [], []
    if n == 0:
        return [EPSILON_TOKEN] * m, list(seq_b)
    if m == 0:
        return list(seq_a), [EPSILON_TOKEN] * n

    # Score matrix (n+1, m+1)
    dp = np.zeros((n + 1, m + 1), dtype=np.float32)
    dp[:, 0] = np.arange(n + 1) * gap_penalty
    dp[0, :] = np.arange(m + 1) * gap_penalty

    # Backtracking pointer matrix (0: diag, 1: up, 2: left)
    ptr = np.zeros((n + 1, m + 1), dtype=np.int32)
    ptr[:, 0] = 1
    ptr[0, :] = 2

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            score_match = dp[i - 1, j - 1] + (
                match_score if seq_a[i - 1] == seq_b[j - 1] else mismatch_penalty
            )
            score_del = dp[i - 1, j] + gap_penalty
            score_ins = dp[i, j - 1] + gap_penalty

            best_score = max(score_match, score_del, score_ins)
            dp[i, j] = best_score

            if best_score == score_match:
                ptr[i, j] = 0
            elif best_score == score_del:
                ptr[i, j] = 1
            else:
                ptr[i, j] = 2

    # Backtrack
    aligned_a: list[str] = []
    aligned_b: list[str] = []
    i, j = n, m

    while i > 0 or j > 0:
        if i > 0 and j > 0 and ptr[i, j] == 0:
            aligned_a.append(seq_a[i - 1])
            aligned_b.append(seq_b[j - 1])
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or ptr[i, j] == 1):
            aligned_a.append(seq_a[i - 1])
            aligned_b.append(EPSILON_TOKEN)
            i -= 1
        else:
            aligned_a.append(EPSILON_TOKEN)
            aligned_b.append(seq_b[j - 1])
            j -= 1

    aligned_a.reverse()
    aligned_b.reverse()

    return aligned_a, aligned_b
