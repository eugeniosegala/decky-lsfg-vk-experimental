import { useState, useEffect, useCallback, useRef } from "react";
import {
  checkLsfgVkInstalled,
  checkLosslessScalingDll,
  getLsfgConfig,
  updateLsfgConfigFromObject,
  type ConfigUpdateResult
} from "../api/lsfgApi";
import { ConfigurationData, getDefaults } from "../config/configSchema";
import { showErrorToast, ToastMessages } from "../utils/toastUtils";
import { createMutationBarrier, mapRecoveryState, type RecoveryState } from "../utils/recoveryState.js";
import t from "../i18n/i18n";

export function useInstallationStatus() {
  const [isInstalled, setIsInstalled] = useState<boolean>(false);
  const [installationStatus, setInstallationStatus] = useState<string>("");
  const [engineUpdateRequired, setEngineUpdateRequired] = useState<boolean>(false);
  const [installedEngineVersion, setInstalledEngineVersion] = useState<string | undefined>();
  const [expectedEngineVersion, setExpectedEngineVersion] = useState<string | undefined>();
  const [recoveryState, setRecoveryState] = useState<RecoveryState>(() =>
    mapRecoveryState({ status_available: false, error_code: "mutation_busy" })
  );

  const checkInstallation = async () => {
    try {
      const status = await checkLsfgVkInstalled();
      const recovery = mapRecoveryState(status);
      setRecoveryState(recovery);
      if (!recovery.available) {
        setInstallationStatus(status.warning || t(
          "STATUS_RECOVERY_UNAVAILABLE",
          "State recovery is pending or unavailable. Changes are disabled until status refreshes."
        ));
        return isInstalled;
      }
      setIsInstalled(Boolean(recovery.trustedInstalled));
      setEngineUpdateRequired(Boolean(status.engine_update_required));
      setInstalledEngineVersion(status.installed_engine_version);
      setExpectedEngineVersion(status.expected_engine_version);
      if (status.installed) {
        setInstallationStatus(t("STATUS_ENGINE_INSTALLED", "Experimental lsfg-vk installed"));
      } else {
        setInstallationStatus(t("STATUS_ENGINE_NOT_INSTALLED", "Experimental lsfg-vk not installed"));
      }
      return status.installed;
    } catch (error) {
      setRecoveryState(mapRecoveryState({ status_available: false, error_code: "mutation_busy" }));
      setInstallationStatus(t("STATUS_RECOVERY_UNAVAILABLE", "State recovery is pending or unavailable. Changes are disabled until status refreshes."));
      setEngineUpdateRequired(false);
      setInstalledEngineVersion(undefined);
      setExpectedEngineVersion(undefined);
      return false;
    }
  };

  useEffect(() => {
    checkInstallation();
  }, []);

  return {
    isInstalled,
    installationStatus,
    engineUpdateRequired,
    installedEngineVersion,
    expectedEngineVersion,
    recoveryState,
    setIsInstalled,
    setInstallationStatus,
    checkInstallation
  };
}

export function useDllDetection() {
  const [dllDetected, setDllDetected] = useState<boolean>(false);
  const [dllDetectionStatus, setDllDetectionStatus] = useState<string>("");

  const checkDllDetection = async () => {
    try {
      const result = await checkLosslessScalingDll();
      setDllDetected(result.detected);
      if (result.detected) {
        setDllDetectionStatus(t("STATUS_LOSSLESS_INSTALLED", "Lossless Scaling installed"));
      } else {
        setDllDetectionStatus(t("STATUS_LOSSLESS_NOT_INSTALLED", "Lossless Scaling not installed"));
      }
    } catch (error) {
      setDllDetectionStatus(t("STATUS_LOSSLESS_NOT_INSTALLED", "Lossless Scaling not installed"));
    }
  };

  useEffect(() => {
    checkDllDetection();
  }, []);

  return {
    dllDetected,
    dllDetectionStatus
  };
}

export function useLsfgConfig() {
  const [config, setConfig] = useState<ConfigurationData>(() => getDefaults());
  const [recoveryState, setRecoveryState] = useState<RecoveryState>(() =>
    mapRecoveryState({ status_available: false, error_code: "refresh_required" })
  );
  const mutationBarrierRef = useRef(createMutationBarrier(true));

  const loadLsfgConfig = useCallback(async () => {
    mutationBarrierRef.current.block();
    setRecoveryState((current) => ({
      ...current,
      available: false,
      mutationsDisabled: true,
    }));
    try {
      const result = await getLsfgConfig();
      const recovery = mapRecoveryState(result);
      setRecoveryState(recovery);
      if (recovery.mutationsDisabled) mutationBarrierRef.current.block();
      else mutationBarrierRef.current.release();
      if (result.success && result.config) {
        // Older installed configurations (or a backend that has not yet been
        // reloaded) may not contain fields introduced by a newer frontend.
        // Preserve the generated defaults for any fields missing from the
        // response so an in-place plugin update never renders undefined values.
        setConfig({ ...getDefaults(), ...result.config });
      } else {
        console.log("lsfg config not available; preserving last known state:", result.error);
      }
    } catch (error) {
      console.error("Error loading lsfg config:", error);
      const unavailable = mapRecoveryState({ status_available: false, error_code: "mutation_busy" });
      setRecoveryState(unavailable);
      mutationBarrierRef.current.block();
    }
  }, []);

  const updateConfig = useCallback(async (newConfig: ConfigurationData): Promise<ConfigUpdateResult> => {
    if (!mutationBarrierRef.current.tryBlock()) {
      return { success: false, error: t("STATUS_RECOVERY_UNAVAILABLE", "State recovery is pending or unavailable. Changes are disabled until status refreshes."), error_code: "refresh_required", retryable: false, recovery_action: "refresh" };
    }
    setRecoveryState((current) => ({ ...current, mutationsDisabled: true }));
    try {
      const normalizedConfig = { ...getDefaults(), ...newConfig };
      const result = await updateLsfgConfigFromObject(normalizedConfig);
      const mutationRecovery = mapRecoveryState(result);
      setRecoveryState({ ...mutationRecovery, mutationsDisabled: true });
      if (result.success) {
        setConfig(normalizedConfig);
      } else {
        showErrorToast(
          ToastMessages.CONFIG_UPDATE_ERROR.title, 
          result.error || ToastMessages.CONFIG_UPDATE_ERROR.body
        );
      }
      await loadLsfgConfig();
      return result;
    } catch (error) {
      const unavailable = mapRecoveryState({ status_available: false, error_code: "mutation_busy" });
      setRecoveryState(unavailable);
      mutationBarrierRef.current.block();
      showErrorToast(ToastMessages.CONFIG_UPDATE_ERROR.title, String(error));
      return { success: false, error: String(error) };
    }
  }, [loadLsfgConfig]);

  const updateField = useCallback(async (fieldName: keyof ConfigurationData, value: boolean | number | string): Promise<ConfigUpdateResult> => {
    const newConfig = { ...config, [fieldName]: value };
    return updateConfig(newConfig);
  }, [config, updateConfig]);

  useEffect(() => {
    loadLsfgConfig();
  }, []);

  return {
    config,
    recoveryState,
    setConfig,
    loadLsfgConfig,
    updateConfig,
    updateField
  };
}
