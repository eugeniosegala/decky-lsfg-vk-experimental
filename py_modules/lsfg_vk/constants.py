"""
Constants for the lsfg-vk plugin.
"""

from pathlib import Path

EXPERIMENTAL_ROOT = ".local/share/decky-lsfg-vk-experimental"
LOCAL_LIB = f"{EXPERIMENTAL_ROOT}/lib"
LOCAL_LIB32 = f"{EXPERIMENTAL_ROOT}/lib32"
VULKAN_LAYER_DIR = f"{EXPERIMENTAL_ROOT}/vulkan/implicit_layer.d"
CONFIG_DIR = ".config/decky-lsfg-vk-experimental"

SCRIPT_NAME = ".local/bin/lsfg-vk-experimental"
DIAGNOSTICS_SCRIPT_NAME = ".local/bin/lsfg-vk-experimental-diagnostics"
DIAGNOSTICS_HELPER_FILENAME = "lsfg-vk-experimental-diagnostics"

# Avoid persistent Gamescope presentation stalls by giving the generated-image
# acquisition path a bounded first wait. During backoff, the engine probes
# availability before scheduling inference and periodically reuses this bound
# to avoid missing the compositor's image-release window indefinitely.
PRESENT_ACQUIRE_TIMEOUT_MS = 50
# After Adaptive recovers from a genuine generated-image timeout, ask the
# application to rebuild its game-owned swapchain. This clears presentation
# state that cannot be reset by recreating only the internal LSFG context.
PRESENT_RECOVERY_RECREATE = 1
CONFIG_FILENAME = "conf.toml"
# The engine reads conf.toml directly, so Decky-only launcher settings must be
# stored separately rather than adding unknown keys to an upstream profile.
WRAPPER_PROFILE_SETTINGS_FILENAME = "profile-wrapper-settings.json"
# Bundled upstream payload filenames. The archive name is read from the packaged
# package.json remote_binary record so the release pin has one source of truth.
LIB_FILENAME = "liblsfg-vk-layer.so"
JSON_FILENAME = "VkLayer_LSFGVK_frame_generation.json"
JSON32_FILENAME = "VkLayer_LSFGVK_frame_generation.x86.json"
CLI_FILENAME = "lsfg-vk-cli"
CLI_DIR = f"{EXPERIMENTAL_ROOT}/bin"

BIN_DIR = "bin"

# Flatpak must load an extension built from this experimental payload rather
# than the public Flathub layer. A distinct extension ID and mount point keep
# both plugins installable without one overwriting the other.
FLATPAK_EXTENSION_NAME = "org.freedesktop.Platform.VulkanLayer.lsfgvkexperimental"
FLATPAK_EXTENSION_PREFIX = "/usr/lib/extensions/vulkan/lsfgvkexperimental"
FLATPAK_IMPLICIT_LAYER_DIR = f"{FLATPAK_EXTENSION_PREFIX}/share/vulkan/implicit_layer.d"
FLATPAK_23_08_FILENAME = f"{FLATPAK_EXTENSION_NAME}-23.08.flatpak"
FLATPAK_24_08_FILENAME = f"{FLATPAK_EXTENSION_NAME}-24.08.flatpak"
FLATPAK_25_08_FILENAME = f"{FLATPAK_EXTENSION_NAME}-25.08.flatpak"

# Armada runs Steam through FEX and requires its host launcher to apply the
# game-specific runtime and controller configuration.
ARMADA_DEVICE_ENV = Path("/usr/libexec/armada/device-env")
ARMADA_GAME_LAUNCH = Path("/usr/libexec/armada/armada-game-launch")

STEAM_COMMON_PATH = Path("steamapps/common/Lossless Scaling")
LOSSLESS_DLL_NAME = "Lossless.dll"

ENV_LSFG_DLL_PATH = "LSFG_DLL_PATH"
ENV_XDG_DATA_HOME = "XDG_DATA_HOME"
ENV_HOME = "HOME"
