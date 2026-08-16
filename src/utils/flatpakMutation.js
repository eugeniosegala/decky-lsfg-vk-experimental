const OBSERVED_FIELDS = [
  "config_filesystem",
  "dll_filesystem",
  "wrapper_filesystem",
  "config_filesystem_ready",
  "dll_filesystem_ready",
  "wrapper_filesystem_ready",
  "lsfg_config_env",
  "vk_implicit_layer_path_env",
  "vk_add_implicit_layer_path_env",
];
const FLATPAK_DIAGNOSTIC_LIMIT = 512;

export function boundedFlatpakDetail(value) {
  const raw = value instanceof Error ? value.message : String(value ?? "");
  const normalized = raw
    .replace(/[\p{Cc}\p{Cf}\p{Cs}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  return normalized.length > FLATPAK_DIAGNOSTIC_LIMIT
    ? `${normalized.slice(0, FLATPAK_DIAGNOSTIC_LIMIT - 1)}…`
    : normalized;
}

function trustedState(app) {
  if (!app) return undefined;
  const source = app.status_available === true ? app : app.stale_state;
  if (!source) return undefined;
  return Object.fromEntries(OBSERVED_FIELDS.map((field) => [field, source[field]]));
}

function matchesMutationTarget(app, operation) {
  if (operation === "set") {
    return app.config_filesystem_ready === true
      && app.dll_filesystem_ready === true
      && app.wrapper_filesystem_ready === true
      && app.lsfg_config_env !== true
      && app.vk_implicit_layer_path_env !== true
      && app.vk_add_implicit_layer_path_env !== true;
  }
  if (operation === "remove") {
    return OBSERVED_FIELDS.every((field) => app[field] === false);
  }
  return false;
}

/** Merge a fresh list without converting unavailable observations into false state. */
export function mergeFlatpakApps(previousApps = [], listResult = {}) {
  if (listResult.success !== true || !Array.isArray(listResult.apps)) {
    return {
      apps: previousApps,
      mutationsDisabled: true,
      error: boundedFlatpakDetail(
        listResult.error || "Flatpak application status is unavailable.",
      ),
    };
  }

  const previousById = new Map(previousApps.map((app) => [app.app_id, app]));
  const apps = listResult.apps.map((app) => {
    if (app.status_available === true) {
      return app;
    }

    const priorState = trustedState(previousById.get(app.app_id));
    return {
      ...app,
      stale: Boolean(priorState),
      ...(priorState ? { stale_state: priorState } : {}),
      actionsDisabled: true,
    };
  });

  return { apps, mutationsDisabled: false, error: undefined };
}

/** Run a mutation and exactly one authoritative refresh, regardless of outcome. */
export async function runFlatpakMutation({ mutate, refresh, previousApps = [] }) {
  let mutation;
  let mutationError;
  try {
    mutation = await mutate();
  } catch (error) {
    mutationError = error;
  }

  let refreshResult;
  let refreshError;
  let merged = { apps: previousApps, mutationsDisabled: true };
  try {
    refreshResult = await refresh();
    merged = mergeFlatpakApps(previousApps, refreshResult);
  } catch (error) {
    refreshError = error;
  }

  return {
    mutation,
    mutationError,
    refresh: refreshResult,
    refreshError,
    apps: merged.apps,
    mutationsDisabled: merged.mutationsDisabled,
    refreshMessage: merged.error,
  };
}

/** Return presentation metadata without trusting user-facing backend text as state. */
export function presentFlatpakMutation(result = {}) {
  if (result.success === true && result.outcome === "complete") {
    return {
      kind: "success",
      messageKey: result.warning
        ? "FLATPAK_APPLICATION_VERIFIED_WITH_WARNING"
        : "FLATPAK_APPLICATION_UPDATED",
    };
  }
  if (result.outcome === "partial") {
    return { kind: "error", messageKey: "FLATPAK_STATUS_PARTIAL" };
  }
  if (result.outcome === "unverified") {
    return { kind: "error", messageKey: "FLATPAK_STATUS_UNAVAILABLE" };
  }
  if (result.outcome === "rejected") {
    return { kind: "error", messageKey: "FLATPAK_PRECONDITION_FAILED" };
  }
  return { kind: "error", messageKey: "FLATPAK_APPLICATION_ACTION_FAILED" };
}

/** Present a mutation only after its target has a fresh authoritative status. */
export function presentFlatpakMutationExecution(execution = {}, appId) {
  const refreshedApp = execution.apps?.find((app) => app.app_id === appId);
  const refreshTrusted = execution.refresh?.success === true
    && refreshedApp?.status_available === true;
  const mutation = execution.mutation;
  const targetVerified = refreshTrusted
    && matchesMutationTarget(refreshedApp, mutation?.operation);
  const presentation = presentFlatpakMutation(
    refreshTrusted
      ? (targetVerified ? mutation ?? {} : { outcome: "failed" })
      : { outcome: "unverified" },
  );
  const detail = presentation.kind === "success"
    ? boundedFlatpakDetail(mutation?.warning || mutation?.message)
    : boundedFlatpakDetail(
      (refreshTrusted && !targetVerified
        ? "The refreshed Flatpak state no longer matches the requested change."
        : mutation?.error)
      || execution.mutationError
      || execution.refreshMessage
      || execution.refreshError,
    );
  return { ...presentation, detail, refreshTrusted, targetVerified };
}

/** Describe safe controls for available app state. */
export function describeFlatpakAppActions(app = {}) {
  if (app.status_available !== true || app.actionsDisabled === true) {
    return { status: "unavailable", explicit: [] };
  }

  const prepared = app.config_filesystem_ready === true
    && app.dll_filesystem_ready === true
    && app.wrapper_filesystem_ready === true
    && app.lsfg_config_env !== true
    && app.vk_implicit_layer_path_env !== true
    && app.vk_add_implicit_layer_path_env !== true;
  const anyOverride = OBSERVED_FIELDS.some((field) => app[field] === true);

  if (prepared) return { status: "prepared", toggle: "remove", explicit: [] };
  if (!anyOverride) return { status: "none", toggle: "set", explicit: [] };
  return { status: "partial", explicit: ["set", "remove"] };
}

/** Serialize mutation plus refresh so a late older refresh cannot win. */
export function createFlatpakMutationQueue() {
  let tail = Promise.resolve();
  return {
    run(arguments_) {
      const operation = tail.then(() => runFlatpakMutation(arguments_));
      tail = operation.catch(() => undefined);
      return operation;
    },
  };
}
