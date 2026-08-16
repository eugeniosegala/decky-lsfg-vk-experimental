"""
Constants for the lsfg-vk plugin.
"""

from pathlib import Path

EXPERIMENTAL_ROOT = ".local/share/decky-lsfg-vk-experimental"
LOCAL_LIB = f"{EXPERIMENTAL_ROOT}/lib"
LOCAL_LIB32 = f"{EXPERIMENTAL_ROOT}/lib32"
VULKAN_LAYER_DIR = f"{EXPERIMENTAL_ROOT}/vulkan/implicit_layer.d"
USER_VULKAN_LAYER_DIR = ".local/share/vulkan/implicit_layer.d"
USER_VULKAN_EXPLICIT_LAYER_DIR = ".local/share/vulkan/explicit_layer.d"
CONFIG_DIR = ".config/decky-lsfg-vk-experimental"

SCRIPT_NAME = ".local/bin/lsfg-vk-experimental"
DIAGNOSTICS_SCRIPT_NAME = ".local/bin/lsfg-vk-experimental-diagnostics"
DIAGNOSTICS_HELPER_FILENAME = "lsfg-vk-experimental-diagnostics"

# Avoid persistent Gamescope presentation stalls by giving the generated-image
# acquisition path a bounded first wait. During backoff, the engine probes
# availability before scheduling inference and periodically reuses this bound
# to avoid missing the compositor's image-release window indefinitely.
PRESENT_ACQUIRE_TIMEOUT_MS = 50
CONFIG_FILENAME = "conf.toml"
# The engine reads conf.toml directly, so Decky-only launcher settings must be
# stored separately rather than adding unknown keys to an upstream profile.
WRAPPER_PROFILE_SETTINGS_FILENAME = "profile-wrapper-settings.json"
FLATPAK_OVERRIDE_OWNERSHIP_FILENAME = "flatpak-override-ownership.json"
# Bundled experimental payload filenames. The archive name is read from the packaged
# package.json remote_binary record so the release pin has one source of truth.
LIB_FILENAME = "liblsfg-vk-layer.so"
EXPERIMENTAL_LAYER_NAME = "VK_LAYER_LSFGVK_experimental_frame_generation"
# Obsolete format-22 explicit meta-layer. Retain only its filename so upgrades
# and uninstall can remove it; HDR now uses SteamOS' normal implicit WSI path.
HDR_META_JSON_FILENAME_64 = "VkLayer_DECKY_LSFGVK_experimental_hdr_stack.x86_64.json"
EXPERIMENTAL_LAYER_ENABLE_ENV = "ENABLE_LSFGVK_EXPERIMENTAL"
EXPERIMENTAL_LAYER_DISABLE_ENV = "DISABLE_LSFGVK_EXPERIMENTAL"
EXPERIMENTAL_LAYER_BUILD_MARKER = (
    b"lsfg-vk: experimental layer active; identity="
    b"VK_LAYER_LSFGVK_experimental_frame_generation; build="
)
JSON_FILENAME = "VkLayer_LSFGVK_experimental_frame_generation.json"
JSON32_FILENAME = "VkLayer_LSFGVK_experimental_frame_generation.x86.json"
LEGACY_PRIVATE_JSON_FILENAMES = (
    "VkLayer_LSFGVK_frame_generation.json",
    "VkLayer_LSFGVK_frame_generation.x86.json",
)
CLI_FILENAME = "lsfg-vk-cli"
CLI_DIR = f"{EXPERIMENTAL_ROOT}/bin"

BIN_DIR = "bin"

# Flatpak must load an extension built from this experimental payload rather
# than the public Flathub layer. A distinct extension ID and mount point keep
# both plugins installable without one overwriting the other.
FLATPAK_EXTENSION_NAME = "org.freedesktop.Platform.VulkanLayer.lsfgvkexperimental"
FLATPAK_EXTENSION_PREFIX = "/usr/lib/extensions/vulkan/lsfgvkexperimental"
FLATPAK_IMPLICIT_LAYER_DIR = f"{FLATPAK_EXTENSION_PREFIX}/share/vulkan/implicit_layer.d"
# Heroic's Flatpak ships Gamescope as a separate Vulkan runtime extension.
# When the per-game UMU wrapper must use VK_IMPLICIT_LAYER_PATH to carry this
# experimental layer into Pressure Vessel, keep Gamescope's manifest in that
# explicit search set as well. Removing it changes ordinary SDR presentation,
# frame limiting, and window integration before LSFG creates a swapchain.
FLATPAK_GAMESCOPE_IMPLICIT_LAYER_DIR = (
    "/usr/lib/extensions/vulkan/gamescope/share/vulkan/implicit_layer.d"
)
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
