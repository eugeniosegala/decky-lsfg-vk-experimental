import { useState } from "react";
import { PanelSectionRow, DialogButton, Focusable } from "@decky/ui";
import { ConfigurationData } from "../config/configSchema";
import { MULTIPLIER } from "../config/generatedConfigSchema";

interface FpsMultiplierControlProps {
  config: ConfigurationData;
  onConfigChange: (fieldName: keyof ConfigurationData, value: boolean | number | string) => Promise<void>;
}

export function FpsMultiplierControl({
  config,
  onConfigChange
}: FpsMultiplierControlProps) {
  const [focusedControl, setFocusedControl] = useState<"decrease" | "increase" | null>(null);

  const multiplierButtonStyle = (isFocused: boolean) => ({
    height: "34px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "2px 0px 0px",
    minWidth: "48px",
    fontSize: "22px",
    fontWeight: "bold",
    color: "#fff7ed",
    background: "linear-gradient(135deg, #a94900 0%, #e87516 55%, #ffae52 100%)",
    border: "1px solid rgba(255, 206, 143, 0.9)",
    borderRadius: "4px",
    outline: isFocused ? "3px solid #ffffff" : "none",
    outlineOffset: "3px",
    boxShadow: isFocused ? "0 0 0 5px rgba(255, 170, 74, 0.45), 0 0 16px rgba(255, 170, 74, 0.95)" : "none",
    transform: isFocused ? "scale(1.04)" : "none",
    scrollMarginTop: "28px",
    scrollMarginBottom: "28px"
  }) as const;

  return (
    <PanelSectionRow>
      <Focusable
        style={{
          marginTop: "8px",
          marginBottom: "8px",
          display: "flex",
          justifyContent: "center",
          alignItems: "center"
        }}
        flow-children="horizontal"
        noFocusRing
      >
        <DialogButton
          style={{
            ...multiplierButtonStyle(focusedControl === "decrease"),
            marginLeft: "0px"
          }}
          onClick={() => onConfigChange(MULTIPLIER, Math.max(2, config.multiplier - 1))}
          onGamepadFocus={() => setFocusedControl("decrease")}
          onGamepadBlur={() => setFocusedControl((current) => current === "decrease" ? null : current)}
          disabled={config.multiplier <= 2}
        >
          −
        </DialogButton>
        <div
          style={{
            marginLeft: "20px",
            marginRight: "20px",
            fontSize: "16px",
            fontWeight: "bold",
            color: config.multiplier > 4 ? "red" : "white",
            minWidth: "60px",
            textAlign: "center"
          }}
        >
          {`${config.multiplier}X`}
        </div>
        <DialogButton
          style={{
            ...multiplierButtonStyle(focusedControl === "increase"),
            marginLeft: "0px"
          }}
          onClick={() => onConfigChange(MULTIPLIER, Math.min(4, config.multiplier + 1))}
          onGamepadFocus={() => setFocusedControl("increase")}
          onGamepadBlur={() => setFocusedControl((current) => current === "increase" ? null : current)}
          disabled={config.multiplier >= 4}
        >
          +
        </DialogButton>
      </Focusable>
    </PanelSectionRow>
  );
}
