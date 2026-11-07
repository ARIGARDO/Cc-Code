"""Launch the browser interface, or the legacy terminal interface with --tui."""
import argparse
import asyncio


def _entry() -> None:
    parser = argparse.ArgumentParser(description="CcCode coding agent")
    parser.add_argument("--tui", action="store_true", help="use the terminal interface")
    args = parser.parse_args()
    try:
        if args.tui:
            from cccode.app import main
            asyncio.run(main())
        else:
            from cccode.web.server import main
            main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _entry()
