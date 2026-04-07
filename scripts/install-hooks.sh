#!/bin/bash
#
# Git hooks installer for dazzlesum development workflow
# Installs pre-commit hook for versioning and pre-push hook for quality gates
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Dazzlesum Git Hooks Installer${NC}"
echo "===================================="

# Check if we're in a git repository
if [ ! -d ".git" ]; then
    echo -e "${RED}Error:${NC} Not in a git repository. Please run from the root of the dazzlesum repository."
    exit 1
fi

# Check if scripts/hooks directory exists
if [ ! -d "scripts/hooks" ]; then
    echo -e "${RED}Error:${NC} scripts/hooks/ directory not found. Please run from the dazzlesum project root."
    exit 1
fi

# Check if source hooks exist
if [ ! -f "scripts/hooks/pre-commit" ]; then
    echo -e "${RED}Error:${NC} scripts/hooks/pre-commit template not found."
    exit 1
fi

if [ ! -f "scripts/hooks/pre-push" ]; then
    echo -e "${RED}Error:${NC} scripts/hooks/pre-push template not found."
    exit 1
fi

# Create .git/hooks directory if it doesn't exist
mkdir -p .git/hooks

# Function to backup and install a hook
install_hook() {
    local hook_name=$1
    local hook_path=".git/hooks/$hook_name"
    
    # Check if hook already exists
    if [ -f "$hook_path" ]; then
        echo -e "${YELLOW}Warning:${NC} Existing $hook_name hook found."
        echo "Current hook:"
        echo "----------------------------------------"
        head -5 "$hook_path"
        echo "----------------------------------------"
        echo
        read -p "Replace existing $hook_name hook? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}Skipping $hook_name installation.${NC}"
            return 1
        fi
        
        # Backup existing hook
        cp "$hook_path" "$hook_path.backup"
        echo -e "${GREEN}Backed up existing $hook_name hook to:${NC} $hook_path.backup"
    fi
    
    # Install the hook
    cp "scripts/hooks/$hook_name" "$hook_path"
    chmod +x "$hook_path"
    echo -e "${GREEN}Installed $hook_name hook successfully!${NC}"
    return 0
}

# Install both hooks
echo "Installing git hooks..."
echo

install_hook "pre-commit"
echo
install_hook "pre-push"

echo
echo -e "${GREEN}Successfully installed dazzlesum development hooks!${NC}"
echo
echo -e "${BLUE}Installed Hooks:${NC}"
echo "• ${GREEN}pre-commit:${NC} Automatic version string updates"
echo "• ${GREEN}pre-push:${NC} Branch-aware quality validation"
echo
echo -e "${BLUE}Pre-Push Validation Modes:${NC}"
echo "• ${GREEN}main branch:${NC} Strict mode - blocks on lint/test failures"
echo "• ${GREEN}dev branch:${NC} Informational mode - reports issues but allows push"
echo "• ${GREEN}feature branches:${NC} Minimal validation - syntax check only"
echo
echo -e "${BLUE}Version Format:${NC} MAJOR.MINOR.PATCH_(Build#)-YYYYMMDD-CommitHash"
echo -e "${BLUE}Example:${NC} 1.3.4_52-20250629-4e4fd00a"
echo
echo -e "${BLUE}Quality Commands:${NC}"
echo "• ${GREEN}./scripts/check_lint.sh${NC} - Run linting with warnings"
echo "• ${GREEN}./scripts/check_lint.sh --strict${NC} - Run linting in strict mode"
echo "• ${GREEN}./scripts/check_tests.sh${NC} - Run tests with warnings"
echo "• ${GREEN}./scripts/check_tests.sh --strict${NC} - Run tests in strict mode"
echo
echo -e "${BLUE}Bypass Options:${NC}"
echo "• ${GREEN}git push --no-verify${NC} - Skip pre-push validation"
echo "• ${GREEN}git commit --no-verify${NC} - Skip pre-commit hooks"
echo
echo -e "${GREEN}Installation complete!${NC} Try making a commit and push to see the hooks in action."