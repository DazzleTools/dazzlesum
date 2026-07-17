# Contributing to Dazzlesum

Thank you for considering contributing to Dazzlesum! This cross-platform checksum utility benefits from community contributions.

## Code of Conduct

Please be respectful and constructive in all interactions. This project welcomes contributions from developers of all skill levels.

## How Can I Contribute?

### Reporting Bugs

When reporting bugs, please include:

1. **Operating System**: Windows, macOS, Linux distribution and version
2. **Python Version**: Output of `python --version`
3. **Command Used**: The exact dazzlesum command that caused the issue
4. **Expected vs Actual Behavior**: What you expected vs what happened
5. **File Structure**: If relevant, describe the directory structure being processed
6. **Error Output**: Full error messages and stack traces

Use our [bug report template](https://github.com/DazzleTools/dazzlesum/issues/new?template=bug-report.md) to ensure you include all necessary information.

### Suggesting Enhancements

Enhancement suggestions are welcome! Please:

1. Check existing issues to avoid duplicates
2. Use our [feature request template](https://github.com/DazzleTools/dazzlesum/issues/new?template=feature-request.md)
3. Describe the use case and expected behavior
4. Consider cross-platform compatibility (Windows, macOS, Linux)
5. Think about DOS shell compatibility requirements

### Code Contributions

#### Development Setup

1. Fork the repository on GitHub
2. Clone your fork locally
3. Create a new branch for your feature/fix
4. Make your changes
5. Test across platforms if possible
6. Submit a pull request

#### Code Style

- Follow existing code style and patterns
- Maintain DOS compatibility (ASCII output, no Unicode symbols)
- Support cross-platform paths and line endings
- Add docstrings for new functions
- Keep functions focused and testable

#### Testing

Before submitting:

1. Test basic functionality: `python dazzlesum.py --version`
2. Test core features: generation, verification, management operations
3. Test on different file types and directory structures
4. Verify cross-platform compatibility when possible

#### Areas for Contribution

- **Shadow Directory Feature**: Implementation of parallel verification directories
- **Performance Optimization**: Large file handling and memory efficiency
- **Additional Hash Algorithms**: Support for new checksum types
- **Platform-Specific Tools**: Integration with more native checksum utilities
- **Documentation**: User guides, examples, and tutorials
- **Testing**: Automated tests and edge case coverage

### Pull Request Process

1. **Fork and Branch**: Create a feature branch from `dev`
2. **Clear Description**: Explain what your PR does and why
3. **Link Issues**: Reference any related issues
4. **Test Coverage**: Ensure your changes work as expected
5. **Documentation**: Update relevant documentation
6. **Compatibility**: Consider impact on existing users

#### Branch Strategy

This project uses a simple branch strategy:
- `main`: Stable, production-ready code
- `dev`: Development and testing
- Feature branches: Created from `dev`, merged back to `dev`

## Development Notes

### Project Structure

- `dazzlesum.py`: Main application (keep as single file for portability)
- `requirements.txt`: Python dependencies (keep minimal)
- `tests/`: Test files and examples
- `docs/`: User documentation

### DOS Compatibility

This is a core requirement:
- Use ASCII characters only in output
- Avoid Unicode symbols (âœ“, âŒ, etc.)
- Support Windows command prompt and PowerShell
- Handle Windows path separators correctly

### Cross-Platform Considerations

- Path handling: Use `pathlib.Path` for cross-platform compatibility
- Line endings: Support auto-detection and normalization
- File permissions: Handle read-only files gracefully
- Symlinks: Detect and handle safely across platforms

## Getting Help

- **Questions**: Use [GitHub Discussions](https://github.com/DazzleTools/dazzlesum/discussions)
- **Documentation**: Check the [README](README.md) and [docs/](docs/) folder
- **Issues**: Search existing issues before creating new ones

## Recognition

Contributors will be acknowledged in the project documentation. Thank you for helping make Dazzlesum better!
