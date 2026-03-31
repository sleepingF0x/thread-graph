# backend/app/pipeline/slicer.py
from collections import defaultdict
from datetime import timedelta

WINDOW_MINUTES = 30


def slice_messages(messages: list) -> list[list]:
    if not messages:
        return []

    by_id: dict[int, object] = {m.id: m for m in messages}

    # Build adjacency for reply chains (undirected)
    adj: dict[int, set[int]] = defaultdict(set)
    for m in messages:
        if m.reply_to_id and m.reply_to_id in by_id:
            adj[m.id].add(m.reply_to_id)
            adj[m.reply_to_id].add(m.id)

    # BFS to find connected reply-chain components
    visited: set[int] = set()
    components: list[list] = []

    for m in messages:
        if m.id in visited:
            continue
        component = []
        queue = [m.id]
        while queue:
            mid = queue.pop()
            if mid in visited or mid not in by_id:
                continue
            visited.add(mid)
            component.append(by_id[mid])
            queue.extend(adj[mid] - visited)
        components.append(component)

    # Sort each component by timestamp and represent as a sorted list
    sorted_components = [
        sorted(component, key=lambda m: m.ts) for component in components
    ]

    # Sort components by their earliest timestamp so we can merge adjacent ones
    sorted_components.sort(key=lambda c: c[0].ts)

    # Merge components that overlap within the time window
    window = timedelta(minutes=WINDOW_MINUTES)
    merged: list[list] = []

    for component in sorted_components:
        if not merged:
            merged.append(list(component))
            continue
        # Check if the earliest message in this component is within the window
        # of the latest message in the current merged group
        last_ts = max(m.ts for m in merged[-1])
        first_ts = component[0].ts
        if first_ts - last_ts <= window:
            merged[-1].extend(component)
            merged[-1].sort(key=lambda m: m.ts)
        else:
            merged.append(list(component))

    return merged
