import { ButtonItem, PanelSectionRow } from "@decky/ui";
import { FaDownload, FaTrash } from "react-icons/fa";

interface InstallationButtonProps {
  isInstalled: boolean;
  isInstalling: boolean;
  isUninstalling: boolean;
  onInstall: () => void;
  onUninstall: () => void;
  topMargin?: string;
}

export function InstallationButton({
  isInstalled,
  isInstalling,
  isUninstalling,
  onInstall,
  onUninstall,
  topMargin = "0"
}: InstallationButtonProps) {
  const renderButtonContent = () => {
    if (isInstalling) {
      return (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div>Installing experimental LSFG-VK...</div>
        </div>
      );
    }

    if (isUninstalling) {
      return (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div>Removing experimental LSFG-VK...</div>
        </div>
      );
    }

    if (isInstalled) {
      return (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <FaTrash />
          <div>Remove Experimental LSFG-VK</div>
        </div>
      );
    }

    return (
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <FaDownload />
        <div>Install Experimental LSFG-VK (developer build)</div>
      </div>
    );
  };

  return (
    <PanelSectionRow>
      <div style={{ marginTop: topMargin }}>
        <ButtonItem
          layout="below"
          onClick={isInstalled ? onUninstall : onInstall}
          disabled={isInstalling || isUninstalling}
        >
          {renderButtonContent()}
        </ButtonItem>
      </div>
    </PanelSectionRow>
  );
}
