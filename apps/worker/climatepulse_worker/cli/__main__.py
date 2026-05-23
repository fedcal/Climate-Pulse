"""CLI dispatcher for climatepulse_worker.

Enables `python -m climatepulse_worker.cli backfill ...` invocation.

Phase 5 will add `dlq` subcommand here.
"""

import sys


def main() -> None:
    """Top-level CLI dispatcher.

    Dispatches to subcommands based on the first positional argument.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        from climatepulse_worker.cli.backfill import main as backfill_main

        sys.exit(backfill_main(sys.argv[2:]))
    else:
        # No subcommand or unknown subcommand: show help
        print(
            "Usage: climatepulse <subcommand> [options]\n"
            "\n"
            "Available subcommands:\n"
            "  backfill  Backfill weather observations from a source\n"
            "\n"
            "Run `climatepulse backfill --help` for subcommand usage.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
