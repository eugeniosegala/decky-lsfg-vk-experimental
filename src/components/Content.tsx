import { useEffect, useRef, useState, type FocusEvent } from "react";
import { AppOverview, ButtonItem, PanelSection, PanelSectionRow, Router, showModal } from "@decky/ui";
import { useInstallationStatus, useDllDetection, useLsfgConfig } from "../hooks/useLsfgHooks";
import { useProfileManagement } from "../hooks/useProfileManagement";
import { useInstallationActions } from "../hooks/useInstallationActions";
import { StatusDisplay } from "./StatusDisplay";
import { InstallationButton } from "./InstallationButton";
import { ConfigurationSection } from "./ConfigurationSection";
import { ProfileManagement, type ProfileManagementHandle } from "./ProfileManagement";
import { UsageInstructions } from "./UsageInstructions";
import { SmartClipboardButton } from "./SmartClipboardButton";
import { FgmodClipboardButton } from "./FgmodClipboardButton";
import { FpsMultiplierControl } from "./FpsMultiplierControl";
import { NerdStuffModal } from "./NerdStuffModal";
import { FlatpaksModal } from "./FlatpaksModal";
import { ConfigurationData } from "../config/configSchema";
import { recoverState } from "../api/lsfgApi";
import {
  mapRecoveryState,
  refreshRecoveryStates,
  summarizeContentRecoveryStates,
  type RecoveryState,
} from "../utils/recoveryState.js";
import { localDevelopmentBuildInfo } from "../config/devBuildInfo.generated";
import t from "../i18n/i18n";

export function Content() {
  const [mainRunningApp, setMainRunningApp] = useState<AppOverview | undefined>(undefined);
  const [isRefreshingMutation, setIsRefreshingMutation] = useState(false);
  const [isRefreshingStatus, setIsRefreshingStatus] = useState(false);
  const [isRecovering, setIsRecovering] = useState(false);
  const profileManagementRef = useRef<ProfileManagementHandle>(null);
  const [profileComponentRecovery, setProfileComponentRecovery] = useState<RecoveryState>(() =>
    mapRecoveryState({ status_available: false, error_code: "refresh_required" })
  );
  const {
    isInstalled,
    installationStatus,
    engineUpdateRequired,
    installedEngineVersion,
    expectedEngineVersion,
    recoveryState: installationRecovery,
    setIsInstalled,
    setInstallationStatus,
    checkInstallation
  } = useInstallationStatus();

  const { dllDetected, dllDetectionStatus } = useDllDetection();

  const {
    config,
    recoveryState: configRecovery,
    loadLsfgConfig,
    updateField
  } = useLsfgConfig();

  const {
    currentProfile,
    updateProfileConfig,
    loadProfiles,
    recoveryState: profileRecovery,
  } = useProfileManagement();

  const { isInstalling, isUninstalling, handleInstall, handleUninstall } = useInstallationActions();
  const installedStateAvailable = installationRecovery.available && isInstalled;
  const configStateAvailable = installedStateAvailable
    && !configRecovery.mutationsDisabled;
  const profileHookAvailable = configStateAvailable
    && !profileRecovery.mutationsDisabled;
  const recoverySummary = summarizeContentRecoveryStates(
    installationRecovery,
    configRecovery,
    profileRecovery,
    profileComponentRecovery,
    profileHookAvailable,
  );
  const mutationsDisabled = recoverySummary.mutationsDisabled
    || isRefreshingMutation
    || isRefreshingStatus
    || isRecovering
    || isInstalling
    || isUninstalling;
  const stateWarningVisible = recoverySummary.warningVisible;
  const stateWarning = recoverySummary.warning;
  const profileStateAvailable = profileHookAvailable
    && !profileComponentRecovery.mutationsDisabled;

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
    if (mutationsDisabled) return;
    setIsRefreshingMutation(true);
    try {
      if (currentProfile) {
        const newConfig = { ...config, [fieldName]: value };
        await updateProfileConfig(currentProfile, newConfig);
        await Promise.all([loadProfiles(), loadLsfgConfig()]);
      } else {
        await updateField(fieldName, value);
        await loadLsfgConfig();
      }
    } finally {
      setIsRefreshingMutation(false);
    }
  };

  const onInstall = async () => {
    if (mutationsDisabled) return;
    setIsRefreshingMutation(true);
    try {
      await handleInstall(setIsInstalled, setInstallationStatus, loadLsfgConfig);
      await Promise.all([checkInstallation(), loadProfiles(), loadLsfgConfig()]);
    } finally {
      setIsRefreshingMutation(false);
    }
  };

  const onUninstall = async () => {
    if (mutationsDisabled) return;
    setIsRefreshingMutation(true);
    try {
      await handleUninstall(setIsInstalled, setInstallationStatus);
      await Promise.all([checkInstallation(), loadProfiles(), loadLsfgConfig()]);
    } finally {
      setIsRefreshingMutation(false);
    }
  };

  const handleRecovery = async () => {
    if (!recoverySummary.recoveryPending || isRecovering) return;
    setIsRecovering(true);
    try {
      await recoverState();
    } catch (error) {
      console.error("State recovery failed:", error);
    } finally {
      await Promise.all([checkInstallation(), loadProfiles(), loadLsfgConfig()]);
      setIsRecovering(false);
    }
  };

  const handleRefreshStatus = async () => {
    if (!recoverySummary.refreshable || isRefreshingStatus) return;
    setIsRefreshingStatus(true);
    try {
      await refreshRecoveryStates(
        checkInstallation,
        loadProfiles,
        loadLsfgConfig,
        profileHookAvailable
          ? profileManagementRef.current?.refreshStatus
          : undefined,
      );
    } finally {
      setIsRefreshingStatus(false);
    }
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
      {stateWarningVisible && (
        <PanelSectionRow>
          <div style={{ padding: "10px 12px", borderRadius: "6px", background: "rgba(255, 152, 0, 0.18)", border: "1px solid rgba(255, 152, 0, 0.75)", color: "#ffd08a" }}>
            {stateWarning || t("STATUS_RECOVERY_UNAVAILABLE", "State recovery is pending or unavailable. Changes are disabled until status refreshes.")}
            {recoverySummary.recoveryPending && (
              <ButtonItem
                layout="below"
                onClick={handleRecovery}
                disabled={isRecovering}
              >
                {isRecovering
                  ? t("RECOVERY_RETRYING", "Retrying state recovery...")
                  : t("RECOVERY_RETRY", "Retry state recovery")}
              </ButtonItem>
            )}
            {recoverySummary.refreshable && (
              <ButtonItem
                layout="below"
                onClick={handleRefreshStatus}
                disabled={isRefreshingStatus}
              >
                {isRefreshingStatus
                  ? t("RECOVERY_REFRESHING_STATUS", "Refreshing status...")
                  : t("RECOVERY_REFRESH_STATUS", "Refresh status")}
              </ButtonItem>
            )}
          </div>
        </PanelSectionRow>
      )}
      {localDevelopmentBuildInfo && (
        <PanelSectionRow>
          <div
            style={{
              padding: "8px 12px",
              backgroundColor: "rgba(33, 150, 243, 0.16)",
              borderRadius: "4px",
              border: "1px solid rgba(33, 150, 243, 0.5)",
              color: "#a8d8ff",
              fontSize: "13px"
            }}
          >
            <div style={{ fontWeight: "bold", marginBottom: "6px" }}>
              🧪 Local development deployment
            </div>
            <div style={{ marginBottom: "10px", color: "#d6ecff" }}>
              <span style={{ color: "#83bff0" }}>Deployed</span>{" "}
              {new Date(localDevelopmentBuildInfo.generatedAt).toLocaleString()}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <div>
                <div style={{ color: "#83bff0", fontWeight: "600" }}>Decky</div>
                <div>Commit: <code>{localDevelopmentBuildInfo.decky.commit}</code>{localDevelopmentBuildInfo.decky.dirty ? " + local edits" : ""}</div>
                <div>Frontend: {localDevelopmentBuildInfo.decky.frontendDeployed ? "deployed" : "unchanged"}</div>
                <div>Backend: {localDevelopmentBuildInfo.decky.backendDeployed ? "deployed" : "unchanged"}</div>
              </div>
              <div>
                <div style={{ color: "#83bff0", fontWeight: "600" }}>LSFG</div>
                {localDevelopmentBuildInfo.engine ? (
                  <>
                    <div>Commit: <code>{localDevelopmentBuildInfo.engine.commit}</code>{localDevelopmentBuildInfo.engine.dirty ? " + local edits" : ""}</div>
                    <div>
                      64-bit layer: {localDevelopmentBuildInfo.engine.layer64Sha256
                        ? <>deployed · SHA-256 <code>{localDevelopmentBuildInfo.engine.layer64Sha256.slice(0, 12)}</code></>
                        : "unchanged"}
                    </div>
                    <div>
                      32-bit layer: {localDevelopmentBuildInfo.engine.layer32Sha256
                        ? <>deployed · SHA-256 <code>{localDevelopmentBuildInfo.engine.layer32Sha256.slice(0, 12)}</code></>
                        : "unchanged"}
                    </div>
                    <div>
                      Flatpak bundles: {localDevelopmentBuildInfo.engine.flatpakBundlesSha256
                        ? <>23.08, 24.08, 25.08 deployed · SHA-256 <code>{localDevelopmentBuildInfo.engine.flatpakBundlesSha256.slice(0, 12)}</code></>
                        : "unchanged"}
                    </div>
                  </>
                ) : (
                  <div>Unchanged by this deployment</div>
                )}
              </div>
            </div>
          </div>
        </PanelSectionRow>
      )}
      {installedStateAvailable && mainRunningApp && (
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
      {installedStateAvailable && engineUpdateRequired && (
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
      {installationRecovery.available && !isInstalled && (
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

      {profileStateAvailable && (
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

      {profileHookAvailable && (
        <ProfileManagement
          ref={profileManagementRef}
          currentProfile={currentProfile}
          mainRunningApp={mainRunningApp}
          disabled={mutationsDisabled}
          onRecoveryStateChange={setProfileComponentRecovery}
          onProfileChange={async () => {
            await loadProfiles();
            await loadLsfgConfig();
          }}
        />
      )}

      {configStateAvailable && (
        <ConfigurationSection
          config={config}
          onConfigChange={handleConfigChange}
        />
      )}

      {configStateAvailable && (
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

      {installedStateAvailable && (
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
