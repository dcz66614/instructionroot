"""Run the P028 InstructionRoot CLI as a module:

    PYTHONPATH=02_src python -m instructionroot inspect --harness codex --cwd .
"""

from instructionroot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
