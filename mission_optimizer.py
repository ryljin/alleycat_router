import itertools
import math
from typing import Any, Optional


def _matrix_value(matrix: list[list[Optional[float]]], i: int, j: int) -> float:
    value = matrix[i][j]

    if value is None:
        return math.inf

    return float(value)


def _visit_location_index(
    visit_id: str,
    visit_by_id: dict[str, Any],
    location_id_to_index: dict[str, int],
) -> int:
    visit = visit_by_id[visit_id]
    return location_id_to_index[visit.location_id]


def _edge_cost(
    from_visit_id: str,
    to_visit_id: str,
    visit_by_id: dict[str, Any],
    location_id_to_index: dict[str, int],
    matrix: list[list[Optional[float]]],
) -> float:
    from_location_index = _visit_location_index(
        from_visit_id,
        visit_by_id,
        location_id_to_index,
    )

    to_location_index = _visit_location_index(
        to_visit_id,
        visit_by_id,
        location_id_to_index,
    )

    return _matrix_value(matrix, from_location_index, to_location_index)


def rotate_list(values: list[str], offset: int) -> list[str]:
    return values[offset:] + values[:offset]


def add_prerequisite(
    prerequisites: dict[str, set[str]],
    visit_id: str,
    required_before: str,
) -> None:
    if visit_id not in prerequisites:
        prerequisites[visit_id] = set()

    prerequisites[visit_id].add(required_before)


def compile_base_constraints(
    payload: Any,
    loop_rotation_choices: Optional[dict[str, list[str]]] = None,
) -> tuple[dict[str, set[str]], dict[str, str], list[str]]:
    """
    Converts mission constraints into:

    prerequisites:
      visit_id -> set of visit IDs that must already be completed

    forced_next:
      visit_id -> visit ID that must happen immediately next

    warnings:
      non-fatal issues
    """

    visit_ids = {visit.id for visit in payload.visits}

    prerequisites: dict[str, set[str]] = {
        visit.id: set()
        for visit in payload.visits
    }

    forced_next: dict[str, str] = {}
    warnings: list[str] = []

    loop_rotation_choices = loop_rotation_choices or {}

    for constraint in payload.constraints:
        constraint_type = constraint.get("type")

        if constraint_type == "precedence":
            before = constraint.get("before")
            after = constraint.get("after")

            if before in visit_ids and after in visit_ids:
                add_prerequisite(prerequisites, after, before)

        elif constraint_type == "chain":
            chain_ids = constraint.get("visit_ids", [])
            strict_consecutive = bool(constraint.get("strict_consecutive", False))

            for before, after in zip(chain_ids, chain_ids[1:]):
                if before in visit_ids and after in visit_ids:
                    add_prerequisite(prerequisites, after, before)

                    if strict_consecutive:
                        if before in forced_next and forced_next[before] != after:
                            warnings.append(
                                f"Strict chain conflict: '{before}' already forces "
                                f"'{forced_next[before]}', so it cannot also force '{after}'."
                            )
                        else:
                            forced_next[before] = after

        elif constraint_type == "pickup_dropoff":
            pickup = constraint.get("pickup_visit_id")
            dropoff = constraint.get("dropoff_visit_id")

            if pickup in visit_ids and dropoff in visit_ids:
                add_prerequisite(prerequisites, dropoff, pickup)

        elif constraint_type == "unlock":
            unlocked_by = constraint.get("unlocked_by")
            unlocks = constraint.get("unlocks", [])

            if unlocked_by in visit_ids and isinstance(unlocks, list):
                for unlocked_visit in unlocks:
                    if unlocked_visit in visit_ids:
                        add_prerequisite(prerequisites, unlocked_visit, unlocked_by)

        elif constraint_type == "group_completion":
            required_before = constraint.get("required_before", [])
            completion_visit_id = constraint.get("completion_visit_id")

            if completion_visit_id in visit_ids and isinstance(required_before, list):
                for before_visit in required_before:
                    if before_visit in visit_ids:
                        add_prerequisite(
                            prerequisites,
                            completion_visit_id,
                            before_visit,
                        )

        elif constraint_type == "ordered_loop":
            loop_id = constraint.get("id", "ordered_loop")
            loop_visit_ids = constraint.get("visit_ids", [])
            can_start_anywhere = bool(constraint.get("can_start_anywhere", False))

            if not isinstance(loop_visit_ids, list) or len(loop_visit_ids) < 2:
                continue

            if can_start_anywhere:
                chosen_order = loop_rotation_choices.get(loop_id)

                if chosen_order is None:
                    continue

                loop_visit_ids = chosen_order

            for before, after in zip(loop_visit_ids, loop_visit_ids[1:]):
                if before in visit_ids and after in visit_ids:
                    add_prerequisite(prerequisites, after, before)

        else:
            warnings.append(f"Unknown constraint type ignored during optimization: {constraint_type}")

    return prerequisites, forced_next, warnings


def get_ordered_loop_rotation_options(payload: Any) -> list[tuple[str, list[list[str]]]]:
    options: list[tuple[str, list[list[str]]]] = []

    for constraint in payload.constraints:
        if constraint.get("type") != "ordered_loop":
            continue

        loop_id = constraint.get("id", "ordered_loop")
        loop_visit_ids = constraint.get("visit_ids", [])
        can_start_anywhere = bool(constraint.get("can_start_anywhere", False))

        if not isinstance(loop_visit_ids, list) or len(loop_visit_ids) < 2:
            continue

        if can_start_anywhere:
            rotations = [
                rotate_list(loop_visit_ids, offset)
                for offset in range(len(loop_visit_ids))
            ]
        else:
            rotations = [loop_visit_ids]

        options.append((loop_id, rotations))

    return options


def route_cost_for_visit_order(
    visit_order: list[str],
    visit_by_id: dict[str, Any],
    location_id_to_index: dict[str, int],
    matrix: list[list[Optional[float]]],
) -> float:
    total = 0.0

    for from_visit_id, to_visit_id in zip(visit_order, visit_order[1:]):
        edge = _edge_cost(
            from_visit_id=from_visit_id,
            to_visit_id=to_visit_id,
            visit_by_id=visit_by_id,
            location_id_to_index=location_id_to_index,
            matrix=matrix,
        )

        if math.isinf(edge):
            return math.inf

        total += edge

    return total


def solve_greedy_precedence_route(
    payload: Any,
    prerequisites: dict[str, set[str]],
    forced_next: dict[str, str],
    location_id_to_index: dict[str, int],
    duration_matrix: list[list[Optional[float]]],
) -> list[str]:
    visit_by_id = {
        visit.id: visit
        for visit in payload.visits
    }

    required_visit_ids = {
        visit.id
        for visit in payload.visits
        if visit.required
    }

    start_visit_id = payload.start_visit_id
    finish_visit_id = payload.finish_visit_id

    if start_visit_id not in visit_by_id:
        raise ValueError(f"Missing start visit '{start_visit_id}'.")

    if finish_visit_id not in visit_by_id:
        raise ValueError(f"Missing finish visit '{finish_visit_id}'.")

    required_visit_ids.add(start_visit_id)
    required_visit_ids.add(finish_visit_id)

    completed = {start_visit_id}
    unvisited = set(required_visit_ids)
    unvisited.discard(start_visit_id)
    unvisited.discard(finish_visit_id)

    current_visit_id = start_visit_id
    route = [start_visit_id]

    while unvisited:
        forced_visit_id = forced_next.get(current_visit_id)

        if forced_visit_id in unvisited:
            forced_prereqs = prerequisites.get(forced_visit_id, set())

            if not forced_prereqs.issubset(completed):
                missing = sorted(forced_prereqs - completed)
                raise ValueError(
                    f"Strict chain deadlock: '{forced_visit_id}' is forced after "
                    f"'{current_visit_id}', but it is missing prerequisites: {missing}"
                )

            next_visit_id = forced_visit_id

        else:
            available = [
                visit_id
                for visit_id in unvisited
                if prerequisites.get(visit_id, set()).issubset(completed)
            ]

            if not available:
                blocked = {
                    visit_id: sorted(list(prerequisites.get(visit_id, set()) - completed))
                    for visit_id in sorted(unvisited)
                }

                raise ValueError(
                    "No legal next visit found. This usually means the constraints "
                    f"created a cycle or impossible prerequisite. Blocked visits: {blocked}"
                )

            next_visit_id = min(
                available,
                key=lambda candidate: _edge_cost(
                    from_visit_id=current_visit_id,
                    to_visit_id=candidate,
                    visit_by_id=visit_by_id,
                    location_id_to_index=location_id_to_index,
                    matrix=duration_matrix,
                ),
            )

            edge = _edge_cost(
                from_visit_id=current_visit_id,
                to_visit_id=next_visit_id,
                visit_by_id=visit_by_id,
                location_id_to_index=location_id_to_index,
                matrix=duration_matrix,
            )

            if math.isinf(edge):
                raise ValueError(
                    f"No routable path from '{current_visit_id}' to '{next_visit_id}'."
                )

        route.append(next_visit_id)
        completed.add(next_visit_id)
        unvisited.remove(next_visit_id)
        current_visit_id = next_visit_id

    finish_prereqs = prerequisites.get(finish_visit_id, set())

    if not finish_prereqs.issubset(completed):
        missing = sorted(finish_prereqs - completed)
        raise ValueError(
            f"Finish visit '{finish_visit_id}' is missing prerequisites: {missing}"
        )

    route.append(finish_visit_id)

    return route


def optimize_mission_order(
    payload: Any,
    location_id_to_index: dict[str, int],
    duration_matrix: list[list[Optional[float]]],
    distance_matrix: list[list[Optional[float]]],
) -> dict:
    visit_by_id = {
        visit.id: visit
        for visit in payload.visits
    }

    loop_options = get_ordered_loop_rotation_options(payload)

    if loop_options:
        loop_ids = [loop_id for loop_id, _ in loop_options]
        loop_variant_sets = [variants for _, variants in loop_options]
        loop_choice_sets = []

        for combination in itertools.product(*loop_variant_sets):
            loop_choice_sets.append(dict(zip(loop_ids, combination)))
    else:
        loop_choice_sets = [{}]

    best_result: Optional[dict] = None
    failures: list[str] = []

    for loop_rotation_choices in loop_choice_sets:
        try:
            prerequisites, forced_next, warnings = compile_base_constraints(
                payload=payload,
                loop_rotation_choices=loop_rotation_choices,
            )

            visit_order = solve_greedy_precedence_route(
                payload=payload,
                prerequisites=prerequisites,
                forced_next=forced_next,
                location_id_to_index=location_id_to_index,
                duration_matrix=duration_matrix,
            )

            total_duration_seconds = route_cost_for_visit_order(
                visit_order=visit_order,
                visit_by_id=visit_by_id,
                location_id_to_index=location_id_to_index,
                matrix=duration_matrix,
            )

            total_distance_meters = route_cost_for_visit_order(
                visit_order=visit_order,
                visit_by_id=visit_by_id,
                location_id_to_index=location_id_to_index,
                matrix=distance_matrix,
            )

            if math.isinf(total_duration_seconds):
                raise ValueError("Route has infinite duration cost.")

            result = {
                "visit_order": visit_order,
                "total_duration_seconds": total_duration_seconds,
                "total_distance_meters": total_distance_meters,
                "method": "greedy_precedence_with_loop_rotation",
                "loop_rotation_choices": loop_rotation_choices,
                "compiled_prerequisites": {
                    visit_id: sorted(list(values))
                    for visit_id, values in prerequisites.items()
                    if values
                },
                "forced_next": forced_next,
                "warnings": warnings,
            }

            if (
                best_result is None
                or total_duration_seconds < best_result["total_duration_seconds"]
            ):
                best_result = result

        except Exception as error:
            failures.append(str(error))

    if best_result is None:
        raise ValueError(
            "No valid mission route found. Failures: "
            + " | ".join(failures[:10])
        )

    return best_result