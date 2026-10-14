__all__ = ("validate_bool",)


def validate_bool(value: object, *, name: str) -> None:
    if value is not True and value is not False:
        message = f"{name} must be a bool"
        raise TypeError(message)
