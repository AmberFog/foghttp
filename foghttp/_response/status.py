__all__ = (
    "is_client_error_status",
    "is_error_status",
    "is_redirect_status",
    "is_server_error_status",
    "is_success_status",
)

from ..status_codes.client_error import MAX_CLIENT_ERROR_STATUS_CODE, MIN_CLIENT_ERROR_STATUS_CODE
from ..status_codes.redirect import MAX_REDIRECT_STATUS_CODE, MIN_REDIRECT_STATUS_CODE
from ..status_codes.server_error import MAX_SERVER_ERROR_STATUS_CODE, MIN_SERVER_ERROR_STATUS_CODE
from ..status_codes.success import MAX_SUCCESS_STATUS_CODE, MIN_SUCCESS_STATUS_CODE


def is_success_status(status_code: int) -> bool:
    return MIN_SUCCESS_STATUS_CODE <= status_code <= MAX_SUCCESS_STATUS_CODE


def is_redirect_status(status_code: int) -> bool:
    return MIN_REDIRECT_STATUS_CODE <= status_code <= MAX_REDIRECT_STATUS_CODE


def is_client_error_status(status_code: int) -> bool:
    return MIN_CLIENT_ERROR_STATUS_CODE <= status_code <= MAX_CLIENT_ERROR_STATUS_CODE


def is_server_error_status(status_code: int) -> bool:
    return MIN_SERVER_ERROR_STATUS_CODE <= status_code <= MAX_SERVER_ERROR_STATUS_CODE


def is_error_status(status_code: int) -> bool:
    return is_client_error_status(status_code) or is_server_error_status(status_code)
