import { useState } from "react";
import { installLsfgVk, uninstallLsfgVk } from "../api/lsfgApi";
import { 
  showInstallSuccessToast, 
  showInstallErrorToast,
  showUninstallSuccessToast, 
  showUninstallErrorToast 
} from "../utils/toastUtils";
import t from "../i18n/i18n";

export function useInstallationActions() {
  const [isInstalling, setIsInstalling] = useState<boolean>(false);
  const [isUninstalling, setIsUninstalling] = useState<boolean>(false);

  const handleInstall = async (
    setIsInstalled: (value: boolean) => void,
    setInstallationStatus: (value: string) => void,
    reloadConfig?: () => Promise<void>
  ) => {
    setIsInstalling(true);
    setInstallationStatus(t("STATUS_ENGINE_INSTALLING", "Installing experimental lsfg-vk (developer build)..."));

    try {
      const result = await installLsfgVk();
      if (result.success) {
        setIsInstalled(true);
        setInstallationStatus(t("STATUS_ENGINE_INSTALLED", "Experimental lsfg-vk installed"));
        showInstallSuccessToast();

        // Reload lsfg config after installation
        if (reloadConfig) {
          await reloadConfig();
        }
      } else {
        setInstallationStatus(`${t("STATUS_INSTALL_FAILED", "Installation failed:")} ${result.error}`);
        showInstallErrorToast(result.error);
      }
    } catch (error) {
      setInstallationStatus(`${t("STATUS_INSTALL_FAILED", "Installation failed:")} ${error}`);
      showInstallErrorToast(String(error));
    } finally {
      setIsInstalling(false);
    }
  };

  const handleUninstall = async (
    setIsInstalled: (value: boolean) => void,
    setInstallationStatus: (value: string) => void
  ) => {
    setIsUninstalling(true);
    setInstallationStatus(t("STATUS_ENGINE_REMOVING", "Removing experimental lsfg-vk..."));

    try {
      const result = await uninstallLsfgVk();
      if (result.success) {
        setIsInstalled(false);
        setInstallationStatus(t("STATUS_ENGINE_REMOVED", "Experimental lsfg-vk removed successfully!"));
        showUninstallSuccessToast();
      } else {
        setInstallationStatus(`${t("STATUS_UNINSTALL_FAILED", "Uninstallation failed:")} ${result.error}`);
        showUninstallErrorToast(result.error);
      }
    } catch (error) {
      setInstallationStatus(`${t("STATUS_UNINSTALL_FAILED", "Uninstallation failed:")} ${error}`);
      showUninstallErrorToast(String(error));
    } finally {
      setIsUninstalling(false);
    }
  };

  return {
    isInstalling,
    isUninstalling,
    handleInstall,
    handleUninstall
  };
}
