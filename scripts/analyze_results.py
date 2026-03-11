"""
Compute inter-rater reliability metrics from eval results.

Reads a JSONL or CSV export and reports Krippendorff's alpha (ordinal),
Fleiss' kappa, pairwise agreement, and per-judge bias — overall and
per evaluation dimension.

Usage:
    python scripts/analyze_results.py results.jsonl
    python scripts/analyze_results.py results.jsonl --csv > irr_metrics.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["score"] = int(row["score"])
            rows.append(row)
    return rows


def load_data(path: str) -> list[dict]:
    if path.endswith(".csv"):
        return load_csv(path)
    return load_jsonl(path)


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------

def build_matrix(
    data: list[dict],
    dimension: str | None = None,
) -> tuple[list[list[int | None]], list[str]]:
    """
    Build a rater-by-subject matrix.

    Returns (matrix, rater_ids) where matrix[i][j] is the score rater j
    gave to item i (or None if missing).
    """
    # Group: (eval_item_id, dimension) -> {judge_model_id: score}
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    rater_set: set[str] = set()

    for row in data:
        if dimension and row["dimension"] != dimension:
            continue
        key = (row["eval_item_id"], row["dimension"])
        judge = row["judge_model_id"]
        groups[key][judge] = row["score"]
        rater_set.add(judge)

    raters = sorted(rater_set)
    rater_idx = {r: i for i, r in enumerate(raters)}

    matrix = []
    for key in sorted(groups.keys()):
        row = [None] * len(raters)
        for judge, score in groups[key].items():
            row[rater_idx[judge]] = score
        matrix.append(row)

    return matrix, raters


# ---------------------------------------------------------------------------
# Krippendorff's alpha (ordinal)
# ---------------------------------------------------------------------------

def krippendorff_alpha_ordinal(
    matrix: list[list[int | None]],
    min_val: int = 1,
    max_val: int = 5,
) -> float:
    """
    Compute Krippendorff's alpha with ordinal distance metric.

    Uses the standard reliability data formulation:
    alpha = 1 - D_observed / D_expected
    """
    # Collect all value pairs from units with >= 2 ratings
    categories = list(range(min_val, max_val + 1))
    n_cat = len(categories)
    cat_idx = {c: i for i, c in enumerate(categories)}

    # Precompute ordinal distance squared
    # For ordinal data: d(c,k)^2 based on cumulative frequency
    # Simplified: use squared rank difference as ordinal distance
    def ordinal_dist_sq(c: int, k: int) -> float:
        # Number of categories between c and k (inclusive of endpoints)
        ic = cat_idx[c]
        ik = cat_idx[k]
        if ic == ik:
            return 0.0
        low, high = min(ic, ik), max(ic, ik)
        return float((high - low) ** 2)

    # Coincidence matrix
    coincidence = [[0.0] * n_cat for _ in range(n_cat)]
    n_total = 0  # total pairable values

    for row in matrix:
        values = [v for v in row if v is not None]
        m_u = len(values)
        if m_u < 2:
            continue
        n_total += m_u
        for i in range(m_u):
            for j in range(m_u):
                if i != j:
                    ci = cat_idx[values[i]]
                    cj = cat_idx[values[j]]
                    coincidence[ci][cj] += 1.0 / (m_u - 1)

    if n_total == 0:
        return 0.0

    # Marginals
    n_c = [sum(coincidence[c][k] for k in range(n_cat)) for c in range(n_cat)]

    # D_observed
    d_obs = 0.0
    for c in range(n_cat):
        for k in range(n_cat):
            d_obs += coincidence[c][k] * ordinal_dist_sq(categories[c], categories[k])

    # D_expected
    d_exp = 0.0
    for c in range(n_cat):
        for k in range(n_cat):
            d_exp += n_c[c] * n_c[k] * ordinal_dist_sq(categories[c], categories[k])

    if d_exp == 0:
        return 1.0  # perfect agreement

    n_total_float = float(n_total)
    d_exp /= (n_total_float * (n_total_float - 1))
    d_obs /= n_total_float

    return 1.0 - d_obs / d_exp


# ---------------------------------------------------------------------------
# Fleiss' kappa
# ---------------------------------------------------------------------------

def fleiss_kappa(
    matrix: list[list[int | None]],
    min_val: int = 1,
    max_val: int = 5,
) -> float:
    """
    Compute Fleiss' kappa for multiple raters with fixed categories.
    """
    categories = list(range(min_val, max_val + 1))
    k = len(categories)
    cat_idx = {c: i for i, c in enumerate(categories)}

    # Build category count matrix: n_subjects x k
    counts = []
    for row in matrix:
        values = [v for v in row if v is not None]
        if len(values) < 2:
            continue
        c = [0] * k
        for v in values:
            c[cat_idx[v]] += 1
        counts.append((c, len(values)))

    n = len(counts)
    if n == 0:
        return 0.0

    # P_i for each subject
    p_i_sum = 0.0
    for c, n_j in counts:
        p_i = (sum(cj * cj for cj in c) - n_j) / (n_j * (n_j - 1)) if n_j > 1 else 0
        p_i_sum += p_i
    p_bar = p_i_sum / n

    # P_j for each category (proportion of all assignments in category j)
    total_assignments = sum(n_j for _, n_j in counts)
    p_j = [0.0] * k
    for c, _ in counts:
        for j in range(k):
            p_j[j] += c[j]
    p_j = [pj / total_assignments for pj in p_j]

    p_e = sum(pj * pj for pj in p_j)

    if abs(1.0 - p_e) < 1e-10:
        return 1.0  # perfect agreement

    return (p_bar - p_e) / (1.0 - p_e)


# ---------------------------------------------------------------------------
# Pairwise agreement
# ---------------------------------------------------------------------------

def pairwise_agreement(matrix: list[list[int | None]]) -> float:
    """Proportion of rater pairs that give the exact same score."""
    agree = 0
    total = 0
    for row in matrix:
        values = [v for v in row if v is not None]
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                total += 1
                if values[i] == values[j]:
                    agree += 1
    return agree / total if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Per-judge statistics
# ---------------------------------------------------------------------------

def judge_stats(data: list[dict]) -> dict[str, dict]:
    """Compute mean and std per judge."""
    by_judge: dict[str, list[int]] = defaultdict(list)
    for row in data:
        by_judge[row["judge_model_id"]].append(row["score"])

    stats = {}
    for judge, scores in sorted(by_judge.items()):
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        stats[judge] = {"mean": mean, "std": math.sqrt(variance), "n": len(scores)}
    return stats


# ---------------------------------------------------------------------------
# Condition comparison statistics
# ---------------------------------------------------------------------------

def condition_stats(data: list[dict]) -> dict[str, dict]:
    """Compute mean, std, n per condition."""
    by_cond: dict[str, list[int]] = defaultdict(list)
    for row in data:
        by_cond[row["condition"]].append(row["score"])

    stats = {}
    for cond, scores in sorted(by_cond.items()):
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        stats[cond] = {"mean": mean, "std": math.sqrt(variance), "n": len(scores)}
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

DIMENSIONS = [
    "linguistic_correctness",
    "explanation_quality",
    "actionability",
    "level_appropriateness",
    "prioritization_and_focus",
    "conversational_quality",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute inter-rater reliability metrics from eval results."
    )
    parser.add_argument(
        "input", help="Path to results.jsonl or results.csv",
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Output metrics as CSV instead of formatted table",
    )
    args = parser.parse_args()

    data = load_data(args.input)
    if not data:
        print("No data found.", file=sys.stderr)
        sys.exit(1)

    n_items = len(set(r["eval_item_id"] for r in data))
    n_judges = len(set(r["judge_model_id"] for r in data))
    n_scores = len(data)

    if args.csv:
        # CSV output
        writer = csv.writer(sys.stdout)
        writer.writerow(["dimension", "krippendorff_alpha", "fleiss_kappa", "pairwise_agreement_pct", "n_items"])
        for dim in DIMENSIONS:
            mat, _ = build_matrix(data, dimension=dim)
            alpha = krippendorff_alpha_ordinal(mat)
            kappa = fleiss_kappa(mat)
            agree = pairwise_agreement(mat)
            writer.writerow([dim, f"{alpha:.4f}", f"{kappa:.4f}", f"{agree*100:.1f}", len(mat)])
        mat_all, _ = build_matrix(data)
        writer.writerow([
            "OVERALL",
            f"{krippendorff_alpha_ordinal(mat_all):.4f}",
            f"{fleiss_kappa(mat_all):.4f}",
            f"{pairwise_agreement(mat_all)*100:.1f}",
            len(mat_all),
        ])
        return

    # Formatted text output
    print(f"Inter-Rater Reliability Analysis")
    print(f"={'=' * 69}")
    print(f"Items: {n_items}  |  Raters: {n_judges}  |  Scores: {n_scores}  |  Scale: 1-5")
    print()

    header = f"{'Dimension':<30s}  {'Kripp α':>9s}  {'Fleiss κ':>9s}  {'Agree %':>9s}  {'n':>6s}"
    print(header)
    print("-" * len(header))

    for dim in DIMENSIONS:
        mat, _ = build_matrix(data, dimension=dim)
        alpha = krippendorff_alpha_ordinal(mat)
        kappa = fleiss_kappa(mat)
        agree = pairwise_agreement(mat)
        print(f"{dim:<30s}  {alpha:>9.4f}  {kappa:>9.4f}  {agree*100:>8.1f}%  {len(mat):>6d}")

    mat_all, raters = build_matrix(data)
    alpha_all = krippendorff_alpha_ordinal(mat_all)
    kappa_all = fleiss_kappa(mat_all)
    agree_all = pairwise_agreement(mat_all)
    print("-" * len(header))
    print(f"{'OVERALL':<30s}  {alpha_all:>9.4f}  {kappa_all:>9.4f}  {agree_all*100:>8.1f}%  {len(mat_all):>6d}")

    # Per-judge bias
    print()
    print(f"Judge Scoring Bias")
    print(f"={'=' * 69}")
    jstats = judge_stats(data)
    jheader = f"{'Judge':<45s}  {'Mean':>6s}  {'Std':>6s}  {'n':>6s}"
    print(jheader)
    print("-" * len(jheader))
    for judge, s in jstats.items():
        print(f"{judge:<45s}  {s['mean']:>6.3f}  {s['std']:>6.3f}  {s['n']:>6d}")

    # Per-condition summary
    print()
    print(f"Condition Summary")
    print(f"={'=' * 69}")
    cstats = condition_stats(data)
    cheader = f"{'Condition':<15s}  {'Mean':>6s}  {'Std':>6s}  {'n':>6s}"
    print(cheader)
    print("-" * len(cheader))
    for cond, s in cstats.items():
        print(f"{cond:<15s}  {s['mean']:>6.3f}  {s['std']:>6.3f}  {s['n']:>6d}")

    if "baseline" in cstats and "corrected" in cstats:
        delta = cstats["corrected"]["mean"] - cstats["baseline"]["mean"]
        print(f"\nDelta (corrected - baseline): {delta:+.4f}")


if __name__ == "__main__":
    main()
