from __future__ import annotations

import sys

_CLI_COMMANDS = {
    "list", "next", "trigger", "add", "remove", "enable", "disable",
    "suspend", "wake", "toggle", "_run",
}


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in _CLI_COMMANDS:
        from cli import main as cli_main
        cli_main()
    else:
        from gui import run
        run()


if __name__ == "__main__":
    main()
