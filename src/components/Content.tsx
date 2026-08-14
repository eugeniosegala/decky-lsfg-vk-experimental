import { useEffect, useState, type FocusEvent } from "react";
import { AppOverview, ButtonItem, PanelSection, PanelSectionRow, Router, showModal } from "@decky/ui";
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
  const [mainRunningApp, setMainRunningApp] = useState<AppOverview | undefined>(undefined);
  const {
    isInstalled,
    installationStatus,
    engineUpdateRequired,
    installedEngineVersion,
    expectedEngineVersion,
    setIsInstalled,
    setInstallationStatus,
    checkInstallation
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

  useEffect(() => {
    const checkRunningApp = () => {
      setMainRunningApp(Router.MainRunningApp);
    };

    checkRunningApp();
    const interval = setInterval(checkRunningApp, 2000);
    return () => clearInterval(interval);
  }, []);

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

  const onInstall = async () => {
    await handleInstall(setIsInstalled, setInstallationStatus, loadLsfgConfig);
    await checkInstallation();
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
      {isInstalled && mainRunningApp && (
        <PanelSectionRow>
          <div
            style={{
              padding: "8px 12px",
              backgroundColor: "rgba(0, 255, 0, 0.1)",
              borderRadius: "4px",
              border: "1px solid rgba(0, 255, 0, 0.3)",
              fontSize: "13px"
            }}
          >
            <strong>{mainRunningApp.display_name}</strong> {t('CONTENT_RUNNING', 'running.')}{" "}{t('PROFILE_CLOSE_GAME', 'Close game to change profile.')}
          </div>
        </PanelSectionRow>
      )}
      {isInstalled && engineUpdateRequired && (
        <PanelSectionRow>
          <div
            style={{
              marginTop: "8px",
              padding: "12px",
              borderRadius: "8px",
              background: "rgba(255, 152, 0, 0.16)",
              border: "1px solid rgba(255, 152, 0, 0.7)",
              color: "#ffd08a"
            }}
          >
            <div style={{ fontWeight: "bold", marginBottom: "4px" }}>
              {t('CONTENT_ENGINE_UPDATE_REQUIRED', 'Experimental LSFG-VK update required')}
            </div>
            <div style={{ fontSize: "13px", marginBottom: "10px" }}>
              {t('CONTENT_ENGINE_INSTALLED', 'Installed:')} {installedEngineVersion || t('CONTENT_ENGINE_NOT_RECORDED', 'not recorded')}. {t('CONTENT_ENGINE_EXPECTS', 'This plugin expects:')} {expectedEngineVersion || t('CONTENT_ENGINE_BUNDLED_VERSION', 'the bundled version')}.
              {!installedEngineVersion && ` ${t('CONTENT_ENGINE_PREDATES_TRACKING', 'The installed payload predates version tracking.')}`} {t('CONTENT_ENGINE_UPDATE_DESC', "Reinstall the private engine to apply this plugin release's pinned payload. If you use Heroic, refresh its matching runtime extension in Flatpak Extensions afterwards.")}
            </div>
            <ButtonItem
              layout="below"
              onClick={onInstall}
              disabled={isInstalling || isUninstalling}
            >
              {t('CONTENT_REINSTALL_EXPERIMENTAL', 'Reinstall Experimental LSFG-VK')}
            </ButtonItem>
          </div>
        </PanelSectionRow>
      )}
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
            topMargin="16px"
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
              {t("CONTENT_FPS_MULTIPLIER", "Frame Generation Mode")}
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
          mainRunningApp={mainRunningApp}
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
        <div>
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
