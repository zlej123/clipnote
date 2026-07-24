"""Normalization helpers shared by multiple profiles."""


def mmss_to_sec(value):
    """Convert MM:SS or H:MM:SS to seconds, preserving integers and null."""
    if value is None or isinstance(value, int):
        return value
    parts = [int(part) for part in str(value).split(":")]
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds

