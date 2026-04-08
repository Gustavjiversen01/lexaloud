# Security policy

## Reporting a vulnerability

Please report security issues through
[GitHub private vulnerability reporting][advisory]. This is the preferred
channel and is monitored actively.

[advisory]: https://github.com/Gustavjiversen01/lexaloud/security/advisories/new

As a fallback, email **lexaloud-conduct@proton.me** (inbox being provisioned
for v0.1.0).

Please allow up to seven days for an initial response. For critical issues
affecting a running Lexaloud deployment, also indicate in the advisory
whether embargo coordination is needed.

## Supported versions

Security fixes are backported to the latest minor version only.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |
| < 0.1   | ❌        |

## Scope

Lexaloud runs entirely on the user's local machine. It does not make
outbound network requests except for:

1. First-run model downloads from the `kokoro-onnx` GitHub releases page
   (`https://github.com/thewh1teagle/kokoro-onnx/releases`), SHA256-pinned.
2. Nothing else. No telemetry. No usage reporting. No crash reporting.

The daemon binds a **Unix domain socket** at
`$XDG_RUNTIME_DIR/lexaloud/lexaloud.sock` with mode 0700 via
`systemd.service`'s `RuntimeDirectory=` and `RuntimeDirectoryMode=`
directives. Only the owner user's processes can reach the socket.

### In scope
- Privilege escalation from a local unprivileged process through the
  daemon's HTTP API
- Untrusted-input crashes, resource exhaustion, or infinite loops via
  `/speak`, `/pause`, `/resume`, `/stop`, `/skip`, `/back`, `/toggle`
- Concerns about pinned runtime dependencies (report through this channel
  so we can coordinate with upstream)
- Issues in the model-download integrity check or the ORT environment
  guard in `src/lexaloud/models.py`

### Out of scope
- Vulnerabilities in third-party TTS models, phonemizers, or CUDA
  runtime libraries (report those to their upstreams: `kokoro-onnx`,
  `phonemizer-fork`, NVIDIA)
- Social engineering against a contributor
- Physical access attacks against the user's machine

## Disclosure preference

We follow standard coordinated disclosure. Upon report, we will acknowledge
receipt within seven days and work with the reporter on a remediation
timeline. When a fix is shipped, the reporter is credited in `CHANGELOG.md`
unless they prefer to remain anonymous.
