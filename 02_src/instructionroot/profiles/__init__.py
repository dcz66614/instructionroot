"""P028 InstructionRoot Resolve — harness profile package (T003).

Public surface: :func:`instructionroot.resolver.discover`.
The profile modules are importable directly for tests and for the
Rust Oracle's cross-checks (T006 reads the contract, not this
code — the Oracle must stay independent).
"""

from instructionroot.profiles import claude, codex, copilot

__all__ = ["claude", "codex", "copilot"]
