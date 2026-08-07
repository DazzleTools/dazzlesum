# Platform Support

dazzlesum runs on Windows, Linux, macOS, and BSD. This page records what is verified versus designed-for-but-not-yet-verified, plus the platform-specific behavior worth knowing about.

## Verification matrix

| Platform | Status | Notes |
|----------|--------|-------|
| **Windows 10 / 11** | Verified | Primary development platform. Exercised against a 3.38-million-file library. Tested under `cmd.exe`, PowerShell, and Git Bash. |
| **Linux** | CI-tested | The test suite runs on Linux in CI on every push. Not exercised by the maintainer against a large library. |
| **macOS (Intel + Apple Silicon)** | Designed for | No platform-specific code paths are expected to differ from Linux; not yet verified end to end. |
| **BSD (FreeBSD / OpenBSD)** | Likely works | Python 3.9+ is the only hard requirement for the standalone artifact. Untested. |

"Designed for" means the code paths exist and have been reviewed for cross-platform safety -- path handling, subprocess invocation, line-ending policy -- but the maintainer has not run the full flow on that OS. Verification reports and issues are welcome.

## Requirements

- **Python 3.9 or higher** on every platform.
- **The pip package** pulls in `dazzle-lib` and `dazzle-filekit` automatically.
- **The standalone `dazzlesum.py`** needs nothing beyond the standard library. It is generated from the package at build time with its library dependencies inlined, so a single file copy is genuinely self-contained.

## Hashing engine

Hashing runs **in-process through Python's `hashlib`** (OpenSSL-backed) on every platform. Native command-line tools are detected and kept as a fallback for algorithms `hashlib` does not provide, but they are not used for the standard algorithms.

This ordering is deliberate, and it matters for correctness as much as speed. Native tools cost a subprocess spawn per file (roughly 75 ms for `certutil` -- a 130-file tree took 16.7 seconds versus 0.62 seconds in-process), and they hash raw bytes, which bypasses dazzlesum's line-ending normalization. A native digest would therefore disagree with every manifest built by the Python path for text files with CRLF endings. (The old `--force-python` flag was removed in 1.5.1: what it described is now the unconditional default, so it had nothing left to force.)

Detected fallback tools by platform:

| Platform | Tools probed |
|----------|--------------|
| Windows | `fsum`, `certutil` |
| Linux / macOS / BSD | `sha256sum`, `sha1sum`, `sha512sum`, `md5sum`, `shasum`, `md5` (by algorithm) |

## Platform-specific notes

### Windows

- **Console compatibility**: output is ASCII-only, so it renders correctly under codepage 437 (`cmd.exe`) and 1252 (PowerShell) without mojibake.
- **UNC paths**: network paths are handled through the `dazzle-filekit` dependency, whose path-identity layer is backed by [`unctools`](https://github.com/djdarcy/UNCtools). This is a hard dependency of the pip package, not an optional extra.
- **Junctions and symlinks**: reparse points are classified during directory discovery using data already returned by `scandir`, so junction policy costs no extra syscalls. By default, junctions are not followed, which prevents both infinite loops and the double-counting of subtrees reachable by more than one path.
- **Long paths**: extended-length (`\\?\`) prefixes are passed through to the filesystem unchanged.

### Linux, macOS, BSD

- **Native Unix path handling** with no translation layer.
- **Symlink policy** matches the Windows junction policy: not followed by default, with the same loop and double-count protection.
- **Threaded scanning** (`update --threads N`) applies on every platform; workers perform `scandir`/`stat` syscalls while hashing, cache writes, and manifest output stay on the coordinating thread.

## Cross-platform behavior

- **Line endings**: text files are normalized before hashing so that a manifest generated on Windows verifies on Linux and vice versa. Binary files -- detected by null bytes and decoding failure -- are never normalized. This is why the in-process engine is authoritative: it is the only one that applies the policy.
- **Path separators**: manifests store relative paths in a consistent form, so `.shasum` files remain portable between platforms.
- **Encoding**: UTF-8 throughout, with a latin-1 fallback for content that fails to decode.
- **Exit codes**: identical everywhere -- `verify` grades severity from the verified percentage. See the [command reference](command-reference.md#exit-codes).

## Reporting a platform issue

Include your OS and version, `python --version`, and the full output of `dazzlesum -V`. That last one matters: it reports the release, branch, build number, date, and commit hash, which distinguishes a pip install from a clone from a working tree when all three report the same release number.
