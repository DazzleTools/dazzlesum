"""Version information for dazzlesum.

Moved verbatim from dazzlesum.py (v1.5.0-alpha.2), lines 50-64. PHASE and
PRE_RELEASE_NUM lines added so scripts/repokit-common/sync-versions.py can
manage pre-release numbering (pyproject [tool.repokit-common] version-source
points here).
"""

# Version information
# Base semantic version -- managed by scripts/repokit-common/sync-versions.py
# (component-per-line form is what its parser expects)
MAJOR = 1
MINOR = 5
PATCH = 0
PHASE = "alpha"  # Per-MINOR feature set: None, "alpha", "beta", "rc1", etc.
PRE_RELEASE_NUM = 3

# Static version string (updated automatically by git hooks)
__version__ = "1.5.0-alpha_phase1-src-split_94-20260717-e464b9d3"


def get_package_version():
    """Return PEP 440 compliant version for packaging (uses MAJOR.MINOR.PATCH)."""
    return f"{MAJOR}.{MINOR}.{PATCH}"


__author__ = "Dustin Darcy"
