"""Pure deterministic zipper selection for one downstream merge slot.

In v1, `(from_edge, from_lane)` identifies an approach. A v1.1 model with
multi-edge approaches carrying multiple lanes should retain this full pair as
the last-served approach, rather than reducing it to a lane integer.
"""

from collections.abc import Callable, Mapping, MutableMapping, Sequence

Approach = tuple[str, int]
MergeSlot = tuple[str, int]


def arbitrate_merge_slot(
    slot: MergeSlot,
    approaches: Sequence[Approach],
    merge_state: MutableMapping[MergeSlot, Approach],
    waiters: Mapping[Approach, Sequence[int]],
    can_reserve: Callable[[int], bool] | None = None,
) -> tuple[Approach, int] | None:
    """Select at most one waiter, alternating approaches and skipping empties.

    At most one vehicle per slot per step is a deliberate v1 simplification.
    A failed reservation stops arbitration for this slot for the current step.
    """
    ordered = sorted(approaches)
    if not ordered:
        return None
    last = merge_state.get(slot, ordered[-1])
    try:
        start_index = ordered.index(last)
    except ValueError:
        raise ValueError(f"last-served approach {last!r} is not valid for slot {slot!r}") from None

    reserve = can_reserve or (lambda _vehicle_id: True)
    for offset in range(1, len(ordered) + 1):
        approach = ordered[(start_index + offset) % len(ordered)]
        ids = waiters.get(approach, ())
        if not ids:
            continue
        vehicle_id = min(ids)
        if not reserve(vehicle_id):
            break
        merge_state[slot] = approach
        return approach, vehicle_id
    return None
