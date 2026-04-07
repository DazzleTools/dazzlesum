#!/bin/bash
# Enhanced lint check script with strict mode support

# Detect working Python: prefer python3 with flake8 (Linux/CI), fall back to python (Windows)
if python3 -m flake8 --version >/dev/null 2>&1; then
    PYTHON=python3
elif python -m flake8 --version >/dev/null 2>&1; then
    PYTHON=python
else
    echo "No Python with flake8 found"
    exit 1
fi

STRICT_MODE=false
if [[ "$1" == "--strict" ]]; then
    STRICT_MODE=true
fi

echo "Running flake8 linting check..."
# Match CI behavior: use --count flag which exits with error count
if $PYTHON -m flake8 dazzlesum.py tests/ --exclude=tests/test_runs/ --count --statistics; then
    echo "✅ Flake8 check passed!"
else
    EXIT_CODE=$?
    if [[ "$STRICT_MODE" == "true" ]]; then
        echo "❌ Flake8 check failed (strict mode)! Exit code: $EXIT_CODE"
        exit $EXIT_CODE
    else
        echo "⚠️ Flake8 issues found (non-strict mode) - Exit code: $EXIT_CODE"
        # In non-strict mode for dev branch, we don't fail
        # But we should ensure developers see the issues
    fi
fi

echo "Running Python syntax check..."
if $PYTHON -m py_compile dazzlesum.py; then
    echo "✅ Python syntax check passed!"
else
    echo "❌ Python syntax check failed!"
    exit 1
fi

if [[ "$STRICT_MODE" == "false" ]]; then
    echo "All checks completed (warnings allowed)"
else
    echo "All checks passed - ready to push!"
fi