__all__ = ("app",)

from bench.cli import app


if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt as exc:
        raise SystemExit(130) from exc
