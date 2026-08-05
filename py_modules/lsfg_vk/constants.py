"""
Constants for the lsfg-vk plugin.
"""

from pathlib import Path

EXPERIMENTAL_ROOT = ".local/share/decky-lsfg-vk-experimental"
LOCAL_LIB = f"{EXPERIMENTAL_ROOT}/lib"
VULKAN_LAYER_DIR = f"{EXPERIMENTAL_ROOT}/vulkan/implicit_layer.d"
CONFIG_DIR = ".config/decky-lsfg-vk-experimental"

SCRIPT_NAME = ".local/bin/lsfg-vk-experimental"
CONFIG_FILENAME = "conf.toml"
# Bundled upstream payload names
LIB_FILENAME = "liblsfg-vk-layer.so"
JSON_FILENAME = "VkLayer_LSFGVK_frame_generation.json"
ARCHIVE_FILENAME = "lsfg-vk-2.0.0-dev28-linux.tar.xz"
CLI_FILENAME = "lsfg-vk-cli"
CLI_DIR = f"{EXPERIMENTAL_ROOT}/bin"

BIN_DIR = "bin"

# Armada runs Steam through FEX and requires its host launcher to apply the
# game-specific runtime and controller configuration.
ARMADA_DEVICE_ENV = Path("/usr/libexec/armada/device-env")
ARMADA_GAME_LAUNCH = Path("/usr/libexec/armada/armada-game-launch")

STEAM_COMMON_PATH = Path("steamapps/common/Lossless Scaling")
LOSSLESS_DLL_NAME = "Lossless.dll"

ENV_LSFG_DLL_PATH = "LSFG_DLL_PATH"
ENV_XDG_DATA_HOME = "XDG_DATA_HOME"
ENV_HOME = "HOME"
