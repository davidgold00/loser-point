"""Schema validation (pandera) and cross-source reconciliation checks.

Every table at every pipeline stage boundary (raw -> interim -> processed)
is validated here before downstream code may consume it. A schema failure
halts the pipeline with a human-readable report; it never proceeds silently
on partial or malformed data.
"""
