import itertools
import math
from typing import Optional


def _matrix_value(matrix: list[list[Optional[float]]], i: int, j: int) -> float:
    value = matrix[i][j]

    if value is None:
        return math.inf

    return float(value)


def validate_square_matrix(matrix: list[list[Optional[float]]]) -> None:
    if not matrix:
        raise ValueError("Matrix is empty.")

    size = len(matrix)

    for row in matrix:
        if len(row) != size:
            raise ValueError("Matrix must be square.")


def calculate_path_cost(
    order: list[int],
    matrix: list[list[Optional[float]]],
) -> float:
    total = 0.0

    for current_index, next_index in zip(order, order[1:]):
        edge_cost = _matrix_value(matrix, current_index, next_index)

        if math.isinf(edge_cost):
            return math.inf

        total += edge_cost

    return total


def solve_exact_open_tsp(
    matrix: list[list[Optional[float]]],
    start_index: int,
    finish_index: int,
    visit_indices: list[int],
) -> tuple[list[int], float]:
    best_order: Optional[list[int]] = None
    best_cost = math.inf

    for permutation in itertools.permutations(visit_indices):
        candidate_order = [start_index, *permutation, finish_index]
        candidate_cost = calculate_path_cost(candidate_order, matrix)

        if candidate_cost < best_cost:
            best_order = candidate_order
            best_cost = candidate_cost

    if best_order is None or math.isinf(best_cost):
        raise ValueError("No valid route found.")

    return best_order, best_cost


def solve_nearest_neighbor(
    matrix: list[list[Optional[float]]],
    start_index: int,
    finish_index: int,
    visit_indices: list[int],
) -> list[int]:
    unvisited = set(visit_indices)
    order = [start_index]
    current = start_index

    while unvisited:
        next_index = min(
            unvisited,
            key=lambda candidate: _matrix_value(matrix, current, candidate),
        )

        if math.isinf(_matrix_value(matrix, current, next_index)):
            raise ValueError("No valid nearest-neighbor route found.")

        order.append(next_index)
        unvisited.remove(next_index)
        current = next_index

    order.append(finish_index)

    if math.isinf(calculate_path_cost(order, matrix)):
        raise ValueError("No valid route to finish found.")

    return order


def improve_with_2opt(
    order: list[int],
    matrix: list[list[Optional[float]]],
    max_passes: int = 100,
) -> list[int]:
    best_order = order[:]
    best_cost = calculate_path_cost(best_order, matrix)

    # Keep start and finish fixed.
    for _ in range(max_passes):
        improved = False

        for left in range(1, len(best_order) - 2):
            for right in range(left + 1, len(best_order) - 1):
                candidate = (
                    best_order[:left]
                    + list(reversed(best_order[left : right + 1]))
                    + best_order[right + 1 :]
                )

                candidate_cost = calculate_path_cost(candidate, matrix)

                if candidate_cost < best_cost:
                    best_order = candidate
                    best_cost = candidate_cost
                    improved = True

        if not improved:
            break

    return best_order


def solve_heuristic_open_tsp(
    matrix: list[list[Optional[float]]],
    start_index: int,
    finish_index: int,
    visit_indices: list[int],
) -> tuple[list[int], float]:
    initial_order = solve_nearest_neighbor(
        matrix=matrix,
        start_index=start_index,
        finish_index=finish_index,
        visit_indices=visit_indices,
    )

    improved_order = improve_with_2opt(
        order=initial_order,
        matrix=matrix,
    )

    return improved_order, calculate_path_cost(improved_order, matrix)


def solve_open_tsp(
    matrix: list[list[Optional[float]]],
    start_index: int = 0,
    finish_index: Optional[int] = None,
    visit_indices: Optional[list[int]] = None,
    exact_limit: int = 9,
) -> dict:
    """
    Solves an alleycat-style open TSP.

    Start -> visit every checkpoint once -> Finish

    This does not return to start.
    """

    validate_square_matrix(matrix)

    size = len(matrix)

    if finish_index is None:
        finish_index = size - 1

    if visit_indices is None:
        visit_indices = [
            index
            for index in range(size)
            if index not in {start_index, finish_index}
        ]

    if start_index == finish_index:
        raise ValueError("Start and finish cannot be the same index.")

    if start_index < 0 or start_index >= size:
        raise ValueError("Start index is out of bounds.")

    if finish_index < 0 or finish_index >= size:
        raise ValueError("Finish index is out of bounds.")

    if len(set(visit_indices)) != len(visit_indices):
        raise ValueError("Visit indices contain duplicates.")

    illegal_indices = [
        index
        for index in visit_indices
        if index < 0 or index >= size or index in {start_index, finish_index}
    ]

    if illegal_indices:
        raise ValueError(f"Invalid visit indices: {illegal_indices}")

    if len(visit_indices) <= exact_limit:
        order, cost = solve_exact_open_tsp(
            matrix=matrix,
            start_index=start_index,
            finish_index=finish_index,
            visit_indices=visit_indices,
        )
        method = "exact"
    else:
        order, cost = solve_heuristic_open_tsp(
            matrix=matrix,
            start_index=start_index,
            finish_index=finish_index,
            visit_indices=visit_indices,
        )
        method = "nearest_neighbor_2opt"

    return {
        "order": order,
        "cost": cost,
        "method": method,
        "start_index": start_index,
        "finish_index": finish_index,
        "visit_indices": visit_indices,
    }