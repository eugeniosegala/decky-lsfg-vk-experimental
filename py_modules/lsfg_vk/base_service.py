"""
Base service class with common functionality.
"""

import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Optional, TypeVar, Dict

import decky

from .constants import (
    LOCAL_LIB,
    LOCAL_LIB32,
    VULKAN_LAYER_DIR,
    USER_VULKAN_LAYER_DIR,
    USER_VULKAN_EXPLICIT_LAYER_DIR,
    JSON_FILENAME,
    JSON32_FILENAME,
    HDR_META_JSON_FILENAME_64,
    SCRIPT_NAME,
    DIAGNOSTICS_SCRIPT_NAME,
    CONFIG_DIR,
    CONFIG_FILENAME,
    WRAPPER_PROFILE_SETTINGS_FILENAME,
)

ResponseType = TypeVar('ResponseType', bound=Dict[str, Any])


class BaseService:
    """Base service class with common functionality"""
    
    def __init__(self, logger: Optional[Any] = None):
        """Initialize base service
        
        Args:
            logger: Logger instance, defaults to decky.logger if None
        """
        if logger is None:
            self.log = decky.logger
        else:
            self.log = logger
            
        self.user_home = Path.home()
        self.local_lib_dir = self.user_home / LOCAL_LIB
        self.local_lib32_dir = self.user_home / LOCAL_LIB32
        self.local_share_dir = self.user_home / VULKAN_LAYER_DIR
        self.user_vulkan_layer_dir = self.user_home / USER_VULKAN_LAYER_DIR
        self.user_vulkan_explicit_layer_dir = self.user_home / USER_VULKAN_EXPLICIT_LAYER_DIR
        self.registered_json_file = self.user_vulkan_layer_dir / JSON_FILENAME
        self.registered_json32_file = self.user_vulkan_layer_dir / JSON32_FILENAME
        self.hdr_meta_json_file = (
            self.user_vulkan_explicit_layer_dir / HDR_META_JSON_FILENAME_64
        )
        self.lsfg_script_path = self.user_home / SCRIPT_NAME
        self.lsfg_launch_script_path = self.user_home / SCRIPT_NAME
        self.diagnostics_script_path = self.user_home / DIAGNOSTICS_SCRIPT_NAME
        self.config_dir = self.user_home / CONFIG_DIR
        self.config_file_path = self.config_dir / CONFIG_FILENAME
        self.wrapper_profile_settings_path = self.config_dir / WRAPPER_PROFILE_SETTINGS_FILENAME
    
    def _ensure_directories(self) -> None:
        """Create necessary directories if they don't exist"""
        self.local_lib_dir.mkdir(parents=True, exist_ok=True)
        self.local_lib32_dir.mkdir(parents=True, exist_ok=True)
        self.local_share_dir.mkdir(parents=True, exist_ok=True)
        self.user_vulkan_layer_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.lsfg_script_path.parent.mkdir(parents=True, exist_ok=True)
        self.log.info(
            "Ensured isolated directories exist: %s, %s, %s, %s, %s, %s",
            self.local_lib_dir,
            self.local_lib32_dir,
            self.local_share_dir,
            self.user_vulkan_layer_dir,
            self.config_dir,
            self.lsfg_script_path.parent,
        )
    
    def _remove_if_exists(self, path: Path) -> bool:
        """Remove a file if it exists
        
        Args:
            path: Path to the file to remove
            
        Returns:
            True if file was removed, False if it didn't exist
            
        Raises:
            OSError: If removal fails
        """
        if path.exists():
            try:
                path.unlink()
                self.log.info(f"Removed {path}")
                return True
            except OSError as e:
                self.log.error(f"Failed to remove {path}: {e}")
                raise
        else:
            self.log.info(f"File not found: {path}")
            return False
    
    def _write_file(self, path: Path, content: str, mode: int = 0o644) -> None:
        """Atomically replace a text file with durable same-directory staging.
        
        Args:
            path: Target file path
            content: Content to write
            mode: File permissions (default: 0o644)
            
        Raises:
            OSError: If write fails
        """
        temporary_path = None
        replaced = False
        previous_content: bytes | None = None
        previous_mode = 0
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(metadata.st_mode):
                    raise OSError(f"refusing to replace non-regular file: {path}")
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(path, flags)
                try:
                    opened = os.fstat(descriptor)
                    if (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino):
                        raise OSError(f"file changed while preparing replacement: {path}")
                    chunks = []
                    while chunk := os.read(descriptor, 1024 * 1024):
                        chunks.append(chunk)
                    previous_content = b"".join(chunks)
                    previous_mode = stat.S_IMODE(opened.st_mode)
                finally:
                    os.close(descriptor)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(content)
                file.flush()
                os.fchmod(file.fileno(), mode)
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
            replaced = True
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self.log.info(f"Wrote to {path}")
            
        except (OSError, IOError, PermissionError) as e:
            if replaced:
                rollback_path: Path | None = None
                try:
                    if previous_content is None:
                        path.unlink(missing_ok=True)
                    else:
                        rollback_fd, rollback_name = tempfile.mkstemp(
                            prefix=f".{path.name}.", suffix=".rollback", dir=path.parent
                        )
                        rollback_path = Path(rollback_name)
                        try:
                            view = memoryview(previous_content)
                            while view:
                                written = os.write(rollback_fd, view)
                                view = view[written:]
                            os.fchmod(rollback_fd, previous_mode)
                            try:
                                os.fsync(rollback_fd)
                            except OSError:
                                pass
                        finally:
                            os.close(rollback_fd)
                        os.replace(rollback_path, path)
                        rollback_path = None
                    try:
                        directory_fd = os.open(
                            path.parent,
                            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                        )
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                    except OSError:
                        pass
                finally:
                    if rollback_path is not None:
                        rollback_path.unlink(missing_ok=True)
            self.log.error(f"Failed to write to {path}: {e}")
            raise
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    def _success_response(self, response_type: type, message: str = "", **kwargs) -> Any:
        """Create a standardized success response
        
        Args:
            response_type: The TypedDict response type to create
            message: Success message
            **kwargs: Additional response fields
            
        Returns:
            Success response dict
        """
        response = {
            "success": True,
            "message": message,
            "error": None
        }
        response.update(kwargs)
        return response
    
    def _error_response(self, response_type: type, error: str, message: str = "", **kwargs) -> Any:
        """Create a standardized error response
        
        Args:
            response_type: The TypedDict response type to create
            error: Error description
            message: Optional message
            **kwargs: Additional response fields
            
        Returns:
            Error response dict
        """
        response = {
            "success": False,
            "message": message,
            "error": error
        }
        response.update(kwargs)
        return response

    @staticmethod
    def _recovery_action_for_error(error_code: str) -> str:
        """Return the stable frontend recovery action for an error code."""
        return {
            "mutation_busy": "retry",
            "refresh_required": "refresh",
            "recovery_blocked": "repair_required",
        }.get(error_code, "none")
