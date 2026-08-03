"""Shared mutable runtime state (the monolith's module-level globals).

Extracted verbatim from dazzlesum.py (v1.5.0-alpha.2, commit 3511c56),
lines 239-240, 398-399, 401-402, 404-405, 407-408, 718-719, 721-722. Only import wiring and shared-state references
(``state.<name>``) were adjusted -- no logic changes (Phase 1, AC-R4).
"""


# Global logger instance - will be set up in main()
dazzle_logger = None


# Global color formatter instance - will be set up in main()
color_formatter = None


# Global exit code for verification operations - will be set by verification results
verification_exit_code = 0


# Global flag to track if this is an auto-detected command
is_auto_detected_command = False


# Global verbosity configuration instance
verbosity_config = None


# Global grand totals instance for recursive operations
grand_totals = None


# Global squelch settings for output filtering (initialized by verbosity system)
squelch_settings = None
