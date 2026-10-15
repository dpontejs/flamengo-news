from flanews.models import StandingRow


def standings_window(rows: list[StandingRow], radius: int = 2) -> list[StandingRow]:
    """Flamengo's row plus `radius` rows above and below, shifted at the table edges."""
    ordered = sorted(rows, key=lambda r: r.position)
    index = next((i for i, r in enumerate(ordered) if r.is_flamengo), None)
    if index is None:
        return []
    size = 2 * radius + 1
    start = max(0, min(index - radius, len(ordered) - size))
    return ordered[start : start + size]
