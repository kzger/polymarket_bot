"""Entry point: start the incubation monitoring dashboard."""

from dotenv import load_dotenv

load_dotenv()

from incubation import monitor


def main() -> None:
    monitor.run(interval_seconds=30)


if __name__ == "__main__":
    main()
