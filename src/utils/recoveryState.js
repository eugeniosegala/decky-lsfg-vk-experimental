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

/** Normalize additive recovery metadata without relying on user-facing text. */
export function mapRecoveryState(response = {}) {
  const hasExplicitAvailability = typeof response.status_available === "boolean";
  const hasRecoveryMetadata = RECOVERY_FIELDS.some((field) =>
    Object.prototype.hasOwnProperty.call(response, field),
  );
  const available = hasExplicitAvailability
    ? response.status_available
    : !hasRecoveryMetadata;

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
