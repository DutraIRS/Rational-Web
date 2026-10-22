# Security policy

## Supported versions

Rational Web is in alpha. Security fixes are made on the latest release only.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through
GitHub's *Security → Report a vulnerability* (private advisory) on this repository, and
include:

- the affected version and a description of the issue;
- steps or a minimal app that reproduces it;
- the impact you expect (for example XSS, CSRF bypass, cross-session data access).

You should receive an acknowledgement within 7 days. Once a fix is released, the advisory is
published with credit to the reporter (unless you prefer otherwise).

## Scope

The framework's security model is documented in `docs/security.rst`. Running an app with
`--dev` exposes source code and tracebacks by design, so reports about development mode
being reachable on a public interface are out of scope.
