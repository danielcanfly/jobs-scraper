"""Internal typed service errors for MCP service helpers."""
from __future__ import annotations


class ServiceError(Exception):
    """Base class for internal service errors mapped to public MCP result fields."""

    error_code = "SERVICE_ERROR"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code
        self.message = message

    def as_public_error(self) -> dict[str, str]:
        return {"error_code": self.error_code, "message": self.message}


class ConfigMissing(ServiceError):
    error_code = "CONFIG_MISSING"


class CredentialFileMissing(ServiceError):
    error_code = "CREDENTIAL_FILE_MISSING"


class SheetNotFound(ServiceError):
    error_code = "SHEET_NOT_FOUND"


class RegionNotInitialized(ServiceError):
    error_code = "REGION_NOT_INITIALIZED"


class SchemaMismatch(ServiceError):
    error_code = "SCHEMA_MISMATCH"


class SourceRegionUnsupported(ServiceError):
    error_code = "SOURCE_REGION_UNSUPPORTED"


class OutputContractMissing(ServiceError):
    error_code = "OUTPUT_CONTRACT_MISSING"


class SheetInitFailed(ServiceError):
    error_code = "SHEET_INIT_FAILED"


_ERROR_TYPES: dict[str, type[ServiceError]] = {
    cls.error_code: cls
    for cls in (
        ConfigMissing,
        CredentialFileMissing,
        SheetNotFound,
        RegionNotInitialized,
        SchemaMismatch,
        SourceRegionUnsupported,
        OutputContractMissing,
        SheetInitFailed,
    )
}


def from_public_error(error_code: str, message: str) -> ServiceError:
    """Create a typed internal error from an existing public error code."""
    error_type = _ERROR_TYPES.get(error_code)
    if error_type is None:
        return ServiceError(message, error_code=error_code)
    return error_type(message)


def public_error(exc: ServiceError) -> dict[str, str]:
    return exc.as_public_error()
