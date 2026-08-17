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
import {
  createLatestRequestGate,
  createMutationBarrier,
  mapRecoveryState,
  transientRefreshRecoveryState,
  type RecoveryState,
} from "../utils/recoveryState.js";
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
  const requestGateRef = useRef(createLatestRequestGate());

  const checkInstallation = async () => {
    const requestId = requestGateRef.current.begin();
    try {
      const status = await checkLsfgVkInstalled();
      if (!requestGateRef.current.isLatest(requestId)) return status.installed;
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
      if (!requestGateRef.current.isLatest(requestId)) return false;
      setRecoveryState(transientRefreshRecoveryState());
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
  const requestGateRef = useRef(createLatestRequestGate());

  const checkDllDetection = async () => {
    const requestId = requestGateRef.current.begin();
    try {
      const result = await checkLosslessScalingDll();
      if (!requestGateRef.current.isLatest(requestId)) return;
      setDllDetected(result.detected);
      if (result.detected) {
        setDllDetectionStatus(t("STATUS_LOSSLESS_INSTALLED", "Lossless Scaling installed"));
      } else {
        setDllDetectionStatus(t("STATUS_LOSSLESS_NOT_INSTALLED", "Lossless Scaling not installed"));
      }
    } catch (error) {
      if (!requestGateRef.current.isLatest(requestId)) return;
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
  const requestGateRef = useRef(createLatestRequestGate());

  const loadLsfgConfig = useCallback(async () => {
    const requestId = requestGateRef.current.begin();
    mutationBarrierRef.current.block();
    setRecoveryState((current) => ({
      ...current,
      available: false,
      mutationsDisabled: true,
    }));
    try {
      const result = await getLsfgConfig();
      if (!requestGateRef.current.isLatest(requestId)) return result;
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
      if (!requestGateRef.current.isLatest(requestId)) return;
      console.error("Error loading lsfg config:", error);
      const unavailable = transientRefreshRecoveryState();
      setRecoveryState(unavailable);
      mutationBarrierRef.current.block();
    }
  }, []);

  const updateConfig = useCallback(async (newConfig: ConfigurationData): Promise<ConfigUpdateResult> => {
    if (!mutationBarrierRef.current.tryBlock()) {
      return { success: false, error: t("STATUS_RECOVERY_UNAVAILABLE", "State recovery is pending or unavailable. Changes are disabled until status refreshes."), error_code: "refresh_required", retryable: false, recovery_action: "refresh" };
    }
    // A mutation changes the source of truth. Prevent an older read from
    // reopening the barrier or publishing pre-mutation configuration.
    requestGateRef.current.begin();
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
      const unavailable = transientRefreshRecoveryState();
      setRecoveryState(unavailable);
      mutationBarrierRef.current.block();
      showErrorToast(ToastMessages.CONFIG_UPDATE_ERROR.title, String(error));
      return {
        success: false,
        error: String(error),
        error_code: "mutation_busy",
        retryable: true,
        recovery_action: "refresh",
        status_available: false,
      };
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
