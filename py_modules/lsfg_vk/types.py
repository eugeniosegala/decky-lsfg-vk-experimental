"""
Type definitions for the lsfg-vk plugin responses.
"""

from typing import List, Literal, NotRequired, Optional, TypedDict, Union
from .config_schema import ConfigurationData


class BaseResponse(TypedDict):
    """Base response structure"""
    success: bool
    error_code: NotRequired[str]
    retryable: NotRequired[bool]
    recovery_pending: NotRequired[bool]
    warning: NotRequired[Optional[str]]
    recovery_action: NotRequired[str]
    status_available: NotRequired[bool]


FlatpakOverrideStep = Literal["apply_override"]
FlatpakOverrideOperation = Literal["set", "remove"]
FlatpakOwnershipStatus = Literal[
    "managed", "unmanaged", "unknown", "pending", "blocked"
]


class FlatpakObservedState(TypedDict):
    """Strictly observed per-application Flatpak override state."""

    config_filesystem: bool
    dll_filesystem: bool
    wrapper_filesystem: bool
    config_filesystem_ready: bool
    dll_filesystem_ready: bool
    wrapper_filesystem_ready: bool
    lsfg_config_env: bool
    vk_implicit_layer_path_env: bool
    vk_add_implicit_layer_path_env: bool


class FlatpakOverrideResponseBase(TypedDict):
    """Fields shared by every Flatpak override mutation outcome."""

    app_id: str
    operation: FlatpakOverrideOperation
    message: str
    error: Optional[str]
    warning: Optional[str]
    retryable: bool
    failed_steps: List[FlatpakOverrideStep]
    ownership_status: FlatpakOwnershipStatus


class FlatpakOverrideCompleteResponse(FlatpakOverrideResponseBase):
    success: Literal[True]
    outcome: Literal["complete"]
    status_available: Literal[True]
    observed_state: FlatpakObservedState


class FlatpakOverridePartialResponse(FlatpakOverrideResponseBase):
    success: Literal[False]
    outcome: Literal["partial"]
    status_available: Literal[True]
    error_code: Literal["partial_failure"]
    observed_state: FlatpakObservedState


class FlatpakOverrideFailedResponse(FlatpakOverrideResponseBase):
    success: Literal[False]
    outcome: Literal["failed"]
    status_available: Literal[True]
    error_code: Literal["operation_failed"]
    observed_state: FlatpakObservedState


class FlatpakOverrideRejectedResponse(FlatpakOverrideResponseBase):
    success: Literal[False]
    outcome: Literal["rejected"]
    status_available: Literal[False]
    error_code: Literal["precondition_failed"]


class FlatpakOverrideUnverifiedResponse(FlatpakOverrideResponseBase):
    success: Literal[False]
    outcome: Literal["unverified"]
    status_available: Literal[False]
    error_code: Literal[
        "status_unavailable",
        "operation_busy",
        "ownership_unknown",
        "ownership_pending",
        "ownership_blocked",
    ]


FlatpakOverrideOperationResponse = Union[
    FlatpakOverrideCompleteResponse,
    FlatpakOverridePartialResponse,
    FlatpakOverrideFailedResponse,
    FlatpakOverrideRejectedResponse,
    FlatpakOverrideUnverifiedResponse,
]


class ErrorResponse(BaseResponse):
    """Response structure for errors"""
    error: str


class MessageResponse(BaseResponse):
    """Response structure with message"""
    message: str


class InstallationResponse(BaseResponse):
    """Response for installation operations"""
    message: str
    error: Optional[str]


class UninstallationResponse(BaseResponse):
    """Response for uninstallation operations"""
    message: str
    removed_files: Optional[List[str]]
    error: Optional[str]


class InstallationCheckResponse(TypedDict):
    """Response for installation check"""
    status_available: bool
    installed: bool
    lib_exists: bool
    json_exists: bool
    script_exists: bool
    lib_path: str
    json_path: str
    script_path: str
    installed_engine_version: Optional[str]
    expected_engine_version: Optional[str]
    engine_version_known: bool
    engine_update_required: bool
    error: Optional[str]
    error_code: NotRequired[str]
    retryable: NotRequired[bool]
    recovery_pending: NotRequired[bool]
    warning: NotRequired[Optional[str]]
    recovery_action: NotRequired[str]


class DllDetectionResponse(TypedDict):
    """Response for DLL detection"""
    detected: bool
    path: Optional[str]
    source: Optional[str]
    message: Optional[str]
    error: Optional[str]


class ConfigurationResponse(BaseResponse):
    """Response for configuration operations"""
    config: Optional[ConfigurationData]
    message: Optional[str]
    error: Optional[str]


class ProfileConfig(TypedDict):
    """Configuration for a single profile"""
    exe: str
    config: ConfigurationData


class ProfilesResponse(BaseResponse):
    """Response for profile operations"""
    profiles: Optional[List[str]]
    current_profile: Optional[str]
    message: Optional[str]
    error: Optional[str]


class ProfileResponse(BaseResponse):
    """Response for single profile operations"""
    profile_name: Optional[str]
    message: Optional[str]
    error: Optional[str]
