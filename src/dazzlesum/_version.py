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
PATCH = 1
PHASE = ""  # Per-MINOR feature set: None, "alpha", "beta", "rc1", etc.
PRE_RELEASE_NUM = 7
PROJECT_PHASE = "stable"  # Project-wide: "prealpha", "alpha", "beta", "stable"

# Static version string (updated automatically by git hooks)
__version__ = "1.5.1_main_104-20260807-82e38cfe"


def get_package_version():
    """Return PEP 440 compliant version for packaging (uses MAJOR.MINOR.PATCH)."""
    return f"{MAJOR}.{MINOR}.{PATCH}"


def get_base_version():
    """Return the semantic version string (MAJOR.MINOR.PATCH[-PHASE])."""
    if "_" in __version__:
        return __version__.split("_")[0]
    base = f"{MAJOR}.{MINOR}.{PATCH}"
    if PHASE:
        base = f"{base}-{PHASE}"
    return base


def get_display_version():
    """Return a human-friendly version string with the project phase."""
    base = get_base_version()
    if PROJECT_PHASE and PROJECT_PHASE != "stable":
        return f"{PROJECT_PHASE.upper()} {base}"
    return base


def get_full_display_version():
    """Display version plus the full build string when build metadata
    exists: `1.5.0 (1.5.0_main_99-20260802-2833270f)`.

    The parenthetical (branch, build number, date, commit hash) is what
    tells a user exactly which build they are running -- a pip install, a
    clone, and a worktree can all report the same release number while
    being different code. Falls back to the plain display form when no
    metadata is baked in (a fresh checkout whose hooks have not stamped
    a build).
    """
    display = get_display_version()
    if "_" in __version__:
        return f"{display} ({__version__})"
    return display


# Convenience constants for imports
BASE_VERSION = get_base_version()
DISPLAY_VERSION = get_display_version()
FULL_DISPLAY_VERSION = get_full_display_version()


__author__ = "Dustin Darcy"
