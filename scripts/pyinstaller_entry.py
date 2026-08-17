"""PyInstaller entrypoint that preserves hermes_service_tui package imports."""

from hermes_service_tui.__main__ import main


if __name__ == "__main__":
    main()
