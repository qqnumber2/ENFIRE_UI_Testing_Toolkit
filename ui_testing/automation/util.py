import re

def dotted_code_from_test_name(test_name: str) -> str:
    """
    Extract a leading dotted numeric code like '1.2.3' from test_name.
    Returns 'test' if none is found. Robust against None/empty input.
    """
    if not test_name:
        return "test"
    # Simpler pattern: one or more digits, followed by zero or more (.digits) groups.
    m = re.match(r'^([0-9]+(?:\.[0-9]+)*)', str(test_name))
    if m:
        return m.group(1)
    # Fallback: strip to alnum and dots; default to 'test'
    base = re.sub(r'[^0-9A-Za-z\.]+', '', str(test_name))
    return base or 'test'

def ensure_png_name(group_index: int, shot_index: int, kind: str) -> str:
    """
    Return '0_000O.png' / '0_000T.png' given group index, shot index, and kind ('O' or 'T').
    """
    # Guard types to avoid format exceptions
    try:
        gi = int(group_index)
    except Exception:
        gi = 0
    try:
        si = int(shot_index)
    except Exception:
        si = 0
    k = (kind or 'O')
    return f"{gi}_{si:03d}{k}.png"
