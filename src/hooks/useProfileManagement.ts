import { useState, useEffect, useCallback, useRef } from "react";
import {
  getProfiles,
  createProfile,
  deleteProfile,
  renameProfile,
  setCurrentProfile,
  updateProfileConfig,
  type ProfilesResult,
  type ProfileResult,
  type ConfigUpdateResult
} from "../api/lsfgApi";
import { ConfigurationData } from "../config/configSchema";
import { showSuccessToast, showErrorToast } from "../utils/toastUtils";
import t from "../i18n/i18n";
import {
  createLatestRequestGate,
  createMutationBarrier,
  mapRecoveryState,
  transientRefreshRecoveryState,
  type RecoveryState,
} from "../utils/recoveryState.js";

export function useProfileManagement() {
  const [profiles, setProfiles] = useState<string[]>([]);
  const [currentProfile, setCurrentProfileState] = useState<string>("decky-lsfg-vk");
  const [isLoading, setIsLoading] = useState(false);
  const [recoveryState, setRecoveryState] = useState<RecoveryState>(() =>
    mapRecoveryState({ status_available: false, error_code: "refresh_required" })
  );
  const mutationBarrierRef = useRef(createMutationBarrier(true));
  const requestGateRef = useRef(createLatestRequestGate());

  const beginMutation = (invalidateReads = true) => {
    if (invalidateReads) requestGateRef.current.begin();
    mutationBarrierRef.current.block();
    setRecoveryState((current) => ({ ...current, mutationsDisabled: true }));
  };

  const blockAfterMutationError = () => {
    const unavailable = transientRefreshRecoveryState();
    mutationBarrierRef.current.block();
    setRecoveryState(unavailable);
  };

  const mutationExceptionResult = (error: unknown): ProfileResult => ({
    success: false,
    error: String(error),
    error_code: "mutation_busy",
    retryable: true,
    recovery_action: "refresh",
    status_available: false,
  });

  // Load profiles on hook initialization
  const loadProfiles = useCallback(async () => {
    const requestId = requestGateRef.current.begin();
    beginMutation(false);
    setRecoveryState((current) => ({
      ...current,
      available: false,
      mutationsDisabled: true,
    }));
    try {
      const result: ProfilesResult = await getProfiles();
      if (!requestGateRef.current.isLatest(requestId)) return result;
      const recovery = mapRecoveryState(result);
      setRecoveryState(recovery);
      if (recovery.mutationsDisabled) mutationBarrierRef.current.block();
      else mutationBarrierRef.current.release();
      if (result.success && result.profiles) {
        setProfiles(result.profiles);
        if (result.current_profile) {
          setCurrentProfileState(result.current_profile);
        }
        return result;
      } else {
        console.error("Failed to load profiles:", result.error);
        showErrorToast(t('PROFILE_LOAD_FAILED', 'Failed to load profiles'), result.error || t('PROFILE_UNKNOWN_ERROR', 'Unknown error'));
        return result;
      }
    } catch (error) {
      if (!requestGateRef.current.isLatest(requestId)) {
        return mutationExceptionResult(error);
      }
      const unavailable = transientRefreshRecoveryState();
      setRecoveryState(unavailable);
      mutationBarrierRef.current.block();
      console.error("Error loading profiles:", error);
      showErrorToast(t('PROFILE_LOAD_ERROR', 'Error loading profiles'), String(error));
      return mutationExceptionResult(error);
    }
  }, []);

  const refreshAfterMutation = useCallback(async (result: ProfileResult | ConfigUpdateResult) => {
    const recovery = mapRecoveryState(result);
    mutationBarrierRef.current.block();
    setRecoveryState({ ...recovery, mutationsDisabled: true });
    await loadProfiles();
  }, [loadProfiles]);

  const mutationBlockedResult = (): ProfileResult => ({
    success: false,
    error: t("STATUS_RECOVERY_UNAVAILABLE", "State recovery is pending or unavailable. Changes are disabled until status refreshes."),
    error_code: "refresh_required",
    retryable: false,
    recovery_action: "refresh",
  });

  // Create a new profile
  const handleCreateProfile = useCallback(async (profileName: string, sourceProfile?: string) => {
    if (!mutationBarrierRef.current.tryBlock()) return mutationBlockedResult();
    beginMutation();
    setIsLoading(true);
    try {
      const result: ProfileResult = await createProfile(profileName, sourceProfile || currentProfile);
      await refreshAfterMutation(result);
      if (result.success) {
        // Use the normalized name returned from backend (spaces converted to dashes)
        const actualProfileName = result.profile_name || profileName;
        showSuccessToast(t('PROFILE_CREATED', 'Profile created'), `${t('PROFILE_CREATED_DESC', 'Created profile:')} ${actualProfileName}`);
        return result;
      } else {
        console.error("Failed to create profile:", result.error);
        showErrorToast(t('PROFILE_CREATE_FAILED', 'Failed to create profile'), result.error || t('PROFILE_UNKNOWN_ERROR', 'Unknown error'));
        return result;
      }
    } catch (error) {
      blockAfterMutationError();
      console.error("Error creating profile:", error);
      showErrorToast(t('PROFILE_CREATE_ERROR', 'Error creating profile'), String(error));
      return mutationExceptionResult(error);
    } finally {
      setIsLoading(false);
    }
  }, [currentProfile, refreshAfterMutation]);

  // Delete a profile
  const handleDeleteProfile = useCallback(async (profileName: string) => {
    if (profileName === "decky-lsfg-vk") {
      showErrorToast(t('PROFILE_CANNOT_DELETE_TITLE', 'Cannot delete default profile'), t('PROFILE_CANNOT_DELETE_MSG', 'The default profile cannot be deleted'));
      return { success: false, error: t('PROFILE_CANNOT_DELETE_TITLE', 'Cannot delete default profile') };
    }

    if (!mutationBarrierRef.current.tryBlock()) return mutationBlockedResult();
    beginMutation();

    setIsLoading(true);
    try {
      const result: ProfileResult = await deleteProfile(profileName);
      await refreshAfterMutation(result);
      if (result.success) {
        showSuccessToast(t('PROFILE_DELETED', 'Profile deleted'), `${t('PROFILE_DELETED_DESC', 'Deleted profile:')} ${profileName}`);
        // If we deleted the current profile, it should have switched to default
        if (currentProfile === profileName && !mutationBarrierRef.current.isBlocked()) {
          setCurrentProfileState("decky-lsfg-vk");
        }
        return result;
      } else {
        console.error("Failed to delete profile:", result.error);
        showErrorToast(t('PROFILE_DELETE_FAILED', 'Failed to delete profile'), result.error || t('PROFILE_UNKNOWN_ERROR', 'Unknown error'));
        return result;
      }
    } catch (error) {
      blockAfterMutationError();
      console.error("Error deleting profile:", error);
      showErrorToast(t('PROFILE_DELETE_ERROR', 'Error deleting profile'), String(error));
      return mutationExceptionResult(error);
    } finally {
      setIsLoading(false);
    }
  }, [currentProfile, refreshAfterMutation]);

  // Rename a profile
  const handleRenameProfile = useCallback(async (oldName: string, newName: string) => {
    if (oldName === "decky-lsfg-vk") {
      showErrorToast(t('PROFILE_CANNOT_RENAME_TITLE', 'Cannot rename default profile'), t('PROFILE_CANNOT_RENAME_MSG', 'The default profile cannot be renamed'));
      return { success: false, error: t('PROFILE_CANNOT_RENAME_TITLE', 'Cannot rename default profile') };
    }

    if (!mutationBarrierRef.current.tryBlock()) return mutationBlockedResult();
    beginMutation();

    setIsLoading(true);
    try {
      const result: ProfileResult = await renameProfile(oldName, newName);
      await refreshAfterMutation(result);
      if (result.success) {
        // Use the normalized name returned from backend (spaces converted to dashes)
        const actualNewName = result.profile_name || newName;
        showSuccessToast(t('PROFILE_RENAMED', 'Profile renamed'), `${t('PROFILE_RENAMED_DESC', 'Renamed profile to:')} ${actualNewName}`);
        // Update current profile if it was renamed
        if (currentProfile === oldName && !mutationBarrierRef.current.isBlocked()) {
          setCurrentProfileState(actualNewName);
        }
        return result;
      } else {
        console.error("Failed to rename profile:", result.error);
        showErrorToast(t('PROFILE_RENAME_FAILED', 'Failed to rename profile'), result.error || t('PROFILE_UNKNOWN_ERROR', 'Unknown error'));
        return result;
      }
    } catch (error) {
      blockAfterMutationError();
      console.error("Error renaming profile:", error);
      showErrorToast(t('PROFILE_RENAME_ERROR', 'Error renaming profile'), String(error));
      return mutationExceptionResult(error);
    } finally {
      setIsLoading(false);
    }
  }, [currentProfile, refreshAfterMutation]);

  // Set the current active profile
  const handleSetCurrentProfile = useCallback(async (profileName: string) => {
    if (!mutationBarrierRef.current.tryBlock()) return mutationBlockedResult();
    beginMutation();
    setIsLoading(true);
    try {
      const result: ProfileResult = await setCurrentProfile(profileName);
      await refreshAfterMutation(result);
      if (result.success) {
        if (!mutationBarrierRef.current.isBlocked()) {
          setCurrentProfileState(profileName);
        }
        showSuccessToast(t('PROFILE_SWITCHED', 'Profile switched'), `${t('PROFILE_SWITCHED_DESC', 'Switched to profile:')} ${profileName}`);
        return result;
      } else {
        console.error("Failed to switch profile:", result.error);
        showErrorToast(t('PROFILE_SWITCH_FAILED', 'Failed to switch profile'), result.error || t('PROFILE_UNKNOWN_ERROR', 'Unknown error'));
        return result;
      }
    } catch (error) {
      blockAfterMutationError();
      console.error("Error switching profile:", error);
      showErrorToast(t('PROFILE_SWITCH_ERROR', 'Error switching profile'), String(error));
      return mutationExceptionResult(error);
    } finally {
      setIsLoading(false);
    }
  }, [refreshAfterMutation]);

  // Update configuration for a specific profile
  const handleUpdateProfileConfig = useCallback(async (profileName: string, config: ConfigurationData) => {
    if (!mutationBarrierRef.current.tryBlock()) return mutationBlockedResult();
    beginMutation();
    setIsLoading(true);
    try {
      const result: ConfigUpdateResult = await updateProfileConfig(profileName, config);
      await refreshAfterMutation(result);
      if (result.success) {
        return result;
      } else {
        console.error("Failed to update profile config:", result.error);
        showErrorToast(t('PROFILE_UPDATE_CONFIG_FAILED', 'Failed to update profile config'), result.error || t('PROFILE_UNKNOWN_ERROR', 'Unknown error'));
        return result;
      }
    } catch (error) {
      blockAfterMutationError();
      console.error("Error updating profile config:", error);
      showErrorToast(t('PROFILE_UPDATE_CONFIG_ERROR', 'Error updating profile config'), String(error));
      return mutationExceptionResult(error);
    } finally {
      setIsLoading(false);
    }
  }, [refreshAfterMutation]);

  // Initialize profiles on mount
  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  return {
    profiles,
    currentProfile,
    isLoading,
    recoveryState,
    loadProfiles,
    createProfile: handleCreateProfile,
    deleteProfile: handleDeleteProfile,
    renameProfile: handleRenameProfile,
    setCurrentProfile: handleSetCurrentProfile,
    updateProfileConfig: handleUpdateProfileConfig
  };
}
