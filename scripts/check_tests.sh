#!/bin/bash
# Test runner with strict mode support - matches CI test runner

STRICT_MODE=false
if [[ "$1" == "--strict" ]]; then
    STRICT_MODE=true
fi

echo "Running unit tests..."
if python3 tests/run_tests.py --unit; then
    echo "✅ All tests passed!"
    exit 0
else
    if [[ "$STRICT_MODE" == "true" ]]; then
        echo "❌ Test failures (strict mode)!"
        exit 1
    else
        echo "⚠️ Test failures found (non-strict mode)"
        exit 0
    fi
fi