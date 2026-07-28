"""
Constants for the lsfg-vk plugin.
"""

from pathlib import Path

LOCAL_LIB = ".local/lib"
LOCAL_SHARE_BASE = ".local/share"
VULKAN_LAYER_DIR = ".local/share/vulkan/implicit_layer.d"
CONFIG_DIR = ".config/lsfg-vk"

SCRIPT_NAME = "lsfg"
CONFIG_FILENAME = "conf.toml"
# lsfg-vk v2.0 payload names
LIB_FILENAME = "liblsfg-vk-layer.so"
JSON_FILENAME = "VkLayer_LSFGVK_frame_generation.json"
ARCHIVE_FILENAME = "lsfg-vk-2.0.0-dev28-linux.tar.xz"

BIN_DIR = "bin"

STEAM_COMMON_PATH = Path("steamapps/common/Lossless Scaling")
LOSSLESS_DLL_NAME = "Lossless.dll"

ENV_LSFG_DLL_PATH = "LSFG_DLL_PATH"
ENV_XDG_DATA_HOME = "XDG_DATA_HOME"
ENV_HOME = "HOME"
