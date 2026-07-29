import { PanelSectionRow, ToggleField, SliderField, ButtonItem, TextField } from "@decky/ui";
import { useState, useEffect } from "react";
import { RiArrowDownSFill, RiArrowUpSFill } from "react-icons/ri";
import { ConfigurationData } from "../config/configSchema";
import {
  ACTIVE_IN, ALLOW_FP16, DISABLE_LSFGVK, DLL, FLOW_SCALE, GPU, PERFORMANCE_MODE,
  DXVK_FRAME_RATE, DISABLE_STEAMDECK_MODE, MANGOHUD_WORKAROUND, ENABLE_WSI, ENABLE_ZINK
} from "../config/generatedConfigSchema";

interface ConfigurationSectionProps {
  config: ConfigurationData;
  onConfigChange: (fieldName: keyof ConfigurationData, value: boolean | number | string) => Promise<void>;
}

const WORKAROUNDS_COLLAPSED_KEY = "lsfg-experimental-workarounds-collapsed";
const CONFIG_COLLAPSED_KEY = "lsfg-experimental-config-collapsed";

export function ConfigurationSection({
  config,
  onConfigChange
}: ConfigurationSectionProps) {
  // Initialize with localStorage value, fallback to true if not found
  const [configCollapsed, setConfigCollapsed] = useState(() => {
    try {
      const saved = localStorage.getItem(CONFIG_COLLAPSED_KEY);
      return saved !== null ? JSON.parse(saved) : false;
    } catch {
      return false;
    }
  });

  const [workaroundsCollapsed, setWorkaroundsCollapsed] = useState(() => {
    try {
      const saved = localStorage.getItem(WORKAROUNDS_COLLAPSED_KEY);
      return saved !== null ? JSON.parse(saved) : true;
    } catch {
      return true;
    }
  });

  // Persist workarounds collapse state to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(CONFIG_COLLAPSED_KEY, JSON.stringify(configCollapsed));
    } catch (error) {
      console.warn("Failed to save config collapse state:", error);
    }
  }, [configCollapsed]);

  useEffect(() => {
    try {
      localStorage.setItem(WORKAROUNDS_COLLAPSED_KEY, JSON.stringify(workaroundsCollapsed));
    } catch (error) {
      console.warn("Failed to save workarounds collapse state:", error);
    }
  }, [workaroundsCollapsed]);

  return (
    <>
      <style>
        {`
        .LSFG_ConfigCollapseButton_Container > div > div > div > button,
        .LSFG_ConfigCollapseButton_Container > div > div > div > div > button,
        .LSFG_WorkaroundsCollapseButton_Container > div > div > div > button {
          height: 10px !important;
        }
        .LSFG_WorkaroundsCollapseButton_Container > div > div > div > div > button {
          height: 10px !important;
        }
        `}
      </style>

      {/* Config Section */}
      <PanelSectionRow>
        <div
          style={{
            fontSize: "14px",
            fontWeight: "bold",
            marginTop: "24px",
            marginBottom: "8px",
            color: "white"
          }}
        >
          Config
        </div>
      </PanelSectionRow>

      <PanelSectionRow>
        <div
          className="LSFG_ConfigCollapseButton_Container"
          style={{ marginTop: "4px", marginBottom: "8px" }}
        >
          <ButtonItem
            layout="below"
            bottomSeparator={configCollapsed ? "standard" : "none"}
            onClick={() => setConfigCollapsed(!configCollapsed)}
          >
            {configCollapsed ? (
              <RiArrowDownSFill
                style={{ transform: "translate(0, -13px)", fontSize: "1.5em" }}
              />
            ) : (
              <RiArrowUpSFill
                style={{ transform: "translate(0, -12px)", fontSize: "1.5em" }}
              />
            )}
          </ButtonItem>
        </div>
      </PanelSectionRow>

      {!configCollapsed && (
        <>
          <PanelSectionRow>
            <TextField
              label="Lossless.dll Path"
              description="Optional full path to Lossless.dll. Leave blank to use lsfg-vk automatic discovery."
              value={config.dll}
              onChange={(event) => onConfigChange(DLL, event.currentTarget.value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <SliderField
              label={`Flow Scale (${Math.round(config.flow_scale * 100)}%)`}
              description="Lowers internal motion estimation resolution, improving performance slightly"
              value={config.flow_scale}
              min={0.25}
              max={1.0}
              step={0.01}
              onChange={(value) => onConfigChange(FLOW_SCALE, value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="Disable Frame Generation"
              description="Disables lsfg-vk on the next game launch. Requires a game restart."
              checked={config.disable_lsfgvk}
              onChange={(value) => onConfigChange(DISABLE_LSFGVK, value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <SliderField
              label={`Base FPS Cap${config.dxvk_frame_rate > 0 ? ` (${config.dxvk_frame_rate} FPS)` : " (Off)"}`}
              description="Base framerate cap for DirectX games, before frame multiplier. (Requires game restart to apply)"
              value={config.dxvk_frame_rate}
              min={0}
              max={60}
              step={1}
              onChange={(value) => onConfigChange(DXVK_FRAME_RATE, value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="Allow FP16"
              description="Improves performance on AMD; disable for older NVIDIA GPUs"
              checked={config.allow_fp16}
              onChange={(value) => onConfigChange(ALLOW_FP16, value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <div style={{ paddingTop: "12px" }}>
              <TextField
                label="GPU"
                description="Optional GPU name, vendor:device ID, or PCI bus ID"
                value={config.gpu}
                onChange={(event) => onConfigChange(GPU, event.currentTarget.value)}
              />
            </div>
          </PanelSectionRow>

          <PanelSectionRow>
            <TextField
              label="Active In"
              description="Executable/process names, separated by commas. When set, lsfg-vk matches profiles automatically."
              value={config.active_in}
              onChange={(event) => onConfigChange(ACTIVE_IN, event.currentTarget.value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="Performance Mode"
              description="Uses a lighter FG model to reduce GPU overhead, at the cost of more visual artifacts."
              checked={config.performance_mode}
              onChange={(value) => onConfigChange(PERFORMANCE_MODE, value)}
            />
          </PanelSectionRow>
        </>
      )}

      {/* Workarounds Section */}
      <PanelSectionRow>
        <div
          style={{
            fontSize: "14px",
            fontWeight: "bold",
            marginTop: "24px",
            marginBottom: "8px",
            color: "white"
          }}
        >
          Workarounds
        </div>
      </PanelSectionRow>

      <PanelSectionRow>
        <div
          className="LSFG_WorkaroundsCollapseButton_Container"
          style={{ marginTop: "4px", marginBottom: "8px" }}
        >
          <ButtonItem
            layout="below"
            bottomSeparator={workaroundsCollapsed ? "standard" : "none"}
            onClick={() => setWorkaroundsCollapsed(!workaroundsCollapsed)}
          >
            {workaroundsCollapsed ? (
              <RiArrowDownSFill
                style={{ transform: "translate(0, -13px)", fontSize: "1.5em" }}
              />
            ) : (
              <RiArrowUpSFill
                style={{ transform: "translate(0, -12px)", fontSize: "1.5em" }}
              />
            )}
          </ButtonItem>
        </div>
      </PanelSectionRow>

      {!workaroundsCollapsed && (
        <>
        <PanelSectionRow>
            <ToggleField
              label="Enable WSI"
              description="Re-Enable Gamescope WSI Layer. Requires game restart to apply."
              checked={config.enable_wsi}
              onChange={(value) => onConfigChange(ENABLE_WSI, value)}
            />
          </PanelSectionRow>
          
          <PanelSectionRow>
            <ToggleField
              label="Enable WOW64 for 32-bit games"
              description="Enables PROTON_USE_WOW64=1 for 32-bit games (Use with ProtonGE to fix crashing)"
              checked={config.enable_wow64}
              onChange={(value) => onConfigChange('enable_wow64', value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="Disable Steam Deck mode"
              description="Disables Steam Deck mode (Unlocks hidden settings in some games)"
              checked={config.disable_steamdeck_mode}
              onChange={(value) => onConfigChange(DISABLE_STEAMDECK_MODE, value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="MangoHud Workaround"
              description="Enables a transparent mangohud overlay, sometimes fixes issues with 2X multiplier in game mode"
              checked={config.mangohud_workaround}
              onChange={(value) => onConfigChange(MANGOHUD_WORKAROUND, value)}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="Enable Zink for OpenGL Games"
              description="Use Vulkan-based OpenGL implementation for OpenGL games (may cause crashes or freezes with some games)"
              checked={config.enable_zink}
              onChange={(value) => onConfigChange(ENABLE_ZINK, value)}
            />
          </PanelSectionRow>
        </>
      )}
    </>
  );
}
