const RECOVERY_FIELDS = [
  "error_code",
  "recovery_pending",
  "recovery_action",
  "warning",
];

/** A tiny synchronous gate that closes before an async mutation starts. */
export function createMutationBarrier(initiallyBlocked = true) {
  let blocked = initiallyBlocked;
  return {
    isBlocked: () => blocked,
    tryBlock: () => {
      if (blocked) return false;
      blocked = true;
      return true;
    },
    block: () => {
      blocked = true;
    },
    release: () => {
      blocked = false;
    },
  };
}

/** Issue monotonically increasing request ids so only the newest read may publish state. */
export function createLatestRequestGate() {
  let latestRequestId = 0;
  return {
    begin: () => {
      latestRequestId += 1;
      return latestRequestId;
    },
    isLatest: (requestId) => requestId === latestRequestId,
  };
}

/** Normalize additive recovery metadata without relying on user-facing text. */
export function mapRecoveryState(response = {}) {
  const hasExplicitAvailability = typeof response.status_available === "boolean";
  const hasRecoveryMetadata = RECOVERY_FIELDS.some((field) =>
    Object.prototype.hasOwnProperty.call(response, field),
  );
  const hasLegacyFailure = response.success === false
    || (typeof response.error === "string" && response.error.length > 0);
  const available = hasExplicitAvailability
    ? response.status_available
    : !hasRecoveryMetadata && !hasLegacyFailure;

  let state = "available";
  if (response.error_code === "invalid_persisted_state") {
    state = "invalid-config";
  } else if (!available && response.error_code === "mutation_busy") {
    state = "busy";
  } else if (!available && response.error_code === "recovery_pending") {
    state = "cleanup-pending";
  } else if (!available) {
    state = "blocked";
  }

  let recoveryAction = response.recovery_action ?? "none";
  if (state === "cleanup-pending" && recoveryAction === "retry") {
    recoveryAction = "wait_for_recovery";
  }

  let trustedInstalled;
  if (available && typeof response.installed === "boolean") {
    trustedInstalled = response.installed;
  }

  return {
    state,
    available,
    mutationsDisabled: !available || state === "invalid-config",
    warningVisible: !available || Boolean(response.warning) || state === "invalid-config",
    trustedInstalled,
    recoveryAction,
    errorCode: response.error_code,
    retryable: response.retryable === true && state !== "cleanup-pending",
    recoveryPending: response.recovery_pending === true,
    warning: response.warning,
  };
}

/** Fail closed after a transient RPC exception while keeping status refresh available. */
export function transientRefreshRecoveryState() {
  return mapRecoveryState({
    status_available: false,
    error_code: "mutation_busy",
    retryable: true,
    recovery_action: "refresh",
  });
}

function summarizeRecoveryStates(states) {
  return {
    mutationsDisabled: states.some((state) => state.mutationsDisabled),
    warningVisible: states.some((state) => state.warningVisible),
    warning: states.find((state) => state.warning)?.warning,
    recoveryPending: states.some((state) => state.state === "cleanup-pending"),
    refreshable: states.some((state) =>
      state.retryable && state.recoveryAction === "refresh"
    ),
  };
}

/** Exclude component-local recovery state until that component is mounted. */
export function summarizeContentRecoveryStates(
  installationState,
  configState,
  profileState,
  profileComponentState,
  profileComponentMounted,
) {
  const activeStates = [installationState, configState, profileState];
  if (profileComponentMounted) activeStates.push(profileComponentState);
  return summarizeRecoveryStates(activeStates);
}

/** Refresh every active status source without replaying a mutation. */
export async function refreshRecoveryStates(...refreshers) {
  await Promise.all(
    refreshers
      .filter((refresh) => typeof refresh === "function")
      .map((refresh) => refresh()),
  );
}
