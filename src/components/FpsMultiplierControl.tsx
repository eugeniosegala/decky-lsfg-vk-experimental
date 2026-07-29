import { PanelSectionRow, DialogButton } from "@decky/ui";
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
  const multiplierButtonStyle = {
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
    scrollMarginTop: "28px",
    scrollMarginBottom: "28px"
  } as const;

  return (
    <PanelSectionRow>
      <div
        style={{
          marginTop: "6px",
          marginBottom: "6px",
          display: "flex",
          justifyContent: "center",
          alignItems: "center"
        }}
      >
        <DialogButton
          style={{
            ...multiplierButtonStyle,
            marginLeft: "0px"
          }}
          onClick={() => onConfigChange(MULTIPLIER, Math.max(2, config.multiplier - 1))}
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
            ...multiplierButtonStyle,
            marginLeft: "0px"
          }}
          onClick={() => onConfigChange(MULTIPLIER, Math.min(4, config.multiplier + 1))}
          disabled={config.multiplier >= 4}
        >
          +
        </DialogButton>
      </div>
    </PanelSectionRow>
  );
}
