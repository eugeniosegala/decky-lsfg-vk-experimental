import { useEffect, type FocusEvent } from "react";
import { PanelSection, showModal, ButtonItem, PanelSectionRow } from "@decky/ui";
import { useInstallationStatus, useDllDetection, useLsfgConfig } from "../hooks/useLsfgHooks";
import { useProfileManagement } from "../hooks/useProfileManagement";
import { useInstallationActions } from "../hooks/useInstallationActions";
import { StatusDisplay } from "./StatusDisplay";
import { InstallationButton } from "./InstallationButton";
import { ConfigurationSection } from "./ConfigurationSection";
import { ProfileManagement } from "./ProfileManagement";
import { UsageInstructions } from "./UsageInstructions";
import { SmartClipboardButton } from "./SmartClipboardButton";
import { FgmodClipboardButton } from "./FgmodClipboardButton";
import { FpsMultiplierControl } from "./FpsMultiplierControl";
import { NerdStuffModal } from "./NerdStuffModal";
import { FlatpaksModal } from "./FlatpaksModal";
import { ConfigurationData } from "../config/configSchema";
import t from "../i18n/i18n";

export function Content() {
  const {
    isInstalled,
    installationStatus,
    setIsInstalled,
    setInstallationStatus
  } = useInstallationStatus();

  const { dllDetected, dllDetectionStatus } = useDllDetection();

  const {
    config,
    loadLsfgConfig,
    updateField
  } = useLsfgConfig();

  const {
    currentProfile,
    updateProfileConfig,
    loadProfiles
  } = useProfileManagement();

  const { isInstalling, isUninstalling, handleInstall, handleUninstall } = useInstallationActions();

  useEffect(() => {
    if (isInstalled) {
      loadLsfgConfig();
    }
  }, [isInstalled, loadLsfgConfig]);

  const handleConfigChange = async (fieldName: keyof ConfigurationData, value: boolean | number | string) => {
    if (currentProfile) {
      const newConfig = { ...config, [fieldName]: value };
      const result = await updateProfileConfig(currentProfile, newConfig);
      if (result.success) {
        await loadLsfgConfig();
      }
    } else {
      await updateField(fieldName, value);
    }
  };

  const onInstall = () => {
    handleInstall(setIsInstalled, setInstallationStatus, loadLsfgConfig);
  };

  const onUninstall = () => {
    handleUninstall(setIsInstalled, setInstallationStatus);
  };

  const handleShowNerdStuff = () => {
    showModal(<NerdStuffModal />);
  };

  const handleShowFlatpaks = () => {
    showModal(<FlatpaksModal />);
  };

  const keepFocusedControlVisible = (event: FocusEvent<HTMLDivElement>) => {
    const target = event.target;

    // Decky's controller navigation can move focus before its scroll container
    // has caught up, most noticeably when navigating from the bottom back to
    // the first controls. Centre the newly focused control without animation
    // so the top of the plugin is fully reachable and no scroll requests queue.
    requestAnimationFrame(() => {
      target.scrollIntoView({
        block: "center",
        inline: "nearest",
        behavior: "auto"
      });
    });
  };

  return (
    <div onFocusCapture={keepFocusedControlVisible}>
      <PanelSection>
      {!isInstalled && (
        <>
          <InstallationButton
            isInstalled={isInstalled}
            isInstalling={isInstalling}
            isUninstalling={isUninstalling}
            onInstall={onInstall}
            onUninstall={onUninstall}
          />

          <StatusDisplay
            dllDetected={dllDetected}
            dllDetectionStatus={dllDetectionStatus}
            isInstalled={isInstalled}
            installationStatus={installationStatus}
          />
        </>
      )}

      {isInstalled && (
        <>
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
              {t("CONTENT_FPS_MULTIPLIER", "FPS Multiplier")}
            </div>
          </PanelSectionRow>

          <FpsMultiplierControl
            config={config}
            onConfigChange={handleConfigChange}
          />
        </>
      )}

      {isInstalled && (
        <ProfileManagement
          currentProfile={currentProfile}
          onProfileChange={async () => {
            await loadProfiles();
            await loadLsfgConfig();
          }}
        />
      )}

      {isInstalled && (
        <ConfigurationSection
          config={config}
          onConfigChange={handleConfigChange}
        />
      )}

      {isInstalled && (
        <>
          <SmartClipboardButton />
          <FgmodClipboardButton />
        </>
      )}

      <UsageInstructions />

      <PanelSectionRow>
        <div style={{ marginTop: "24px" }}>
          <ButtonItem
            layout="below"
            onClick={handleShowNerdStuff}
          >
            {t("CONTENT_NERD_STUFF", "Nerd Stuff")}
          </ButtonItem>
        </div>
      </PanelSectionRow>

      <PanelSectionRow>
        <div style={{ marginTop: "8px" }}>
          <ButtonItem
            layout="below"
            onClick={handleShowFlatpaks}
          >
            {t("CONTENT_FLATPAK_SETUP", "Flatpak Setup")}
          </ButtonItem>
        </div>
      </PanelSectionRow>

      {isInstalled && (
        <>
          <StatusDisplay
            dllDetected={dllDetected}
            dllDetectionStatus={dllDetectionStatus}
            isInstalled={isInstalled}
            installationStatus={installationStatus}
            topMargin="24px"
          />

          <InstallationButton
            isInstalled={isInstalled}
            isInstalling={isInstalling}
            isUninstalling={isUninstalling}
            onInstall={onInstall}
            onUninstall={onUninstall}
            topMargin="16px"
          />
        </>
      )}
      </PanelSection>
    </div>
  );
}
