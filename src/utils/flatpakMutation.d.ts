export type FlatpakOverrideOperation = "set" | "remove";
export type FlatpakOverrideOutcome = "complete" | "partial" | "failed" | "rejected" | "unverified";

export interface FlatpakObservedState {
  config_filesystem: boolean;
  dll_filesystem: boolean;
  wrapper_filesystem: boolean;
  config_filesystem_ready: boolean;
  dll_filesystem_ready: boolean;
  wrapper_filesystem_ready: boolean;
  lsfg_config_env: boolean;
  vk_implicit_layer_path_env: boolean;
  vk_add_implicit_layer_path_env: boolean;
}

export type FlatpakOwnershipStatus =
  | "managed"
  | "unmanaged"
  | "unknown"
  | "pending"
  | "blocked";

export interface FlatpakMutationPresentation {
  kind: "success" | "error";
  messageKey: string;
}

export function boundedFlatpakDetail(value: unknown): string;

export interface FlatpakMutationArguments<TMutation, TRefresh, TApp> {
  operation?: FlatpakOverrideOperation;
  mutate: () => Promise<TMutation>;
  refresh: () => Promise<TRefresh>;
  previousApps?: TApp[];
}

export type FlatpakDisplayApp<TApp> = TApp & {
  actionsDisabled?: boolean;
};

export interface FlatpakMutationExecution<TMutation, TRefresh, TApp> {
  operation?: FlatpakOverrideOperation;
  mutation?: TMutation;
  mutationError?: unknown;
  refresh?: TRefresh;
  refreshError?: unknown;
  apps: FlatpakDisplayApp<TApp>[];
  mutationsDisabled: boolean;
  refreshMessage?: string;
}

export function mergeFlatpakApps<TApp>(
  previousApps: TApp[],
  listResult: { success?: boolean; apps?: TApp[]; error?: string },
): { apps: FlatpakDisplayApp<TApp>[]; mutationsDisabled: boolean; error?: string };

export function runFlatpakMutation<TMutation, TRefresh, TApp>(
  arguments_: FlatpakMutationArguments<TMutation, TRefresh, TApp>,
): Promise<FlatpakMutationExecution<TMutation, TRefresh, TApp>>;

export function presentFlatpakMutation(result: {
  success?: boolean;
  outcome?: FlatpakOverrideOutcome;
  warning?: string | null;
}): FlatpakMutationPresentation;

export function presentFlatpakMutationExecution<
  TMutation extends {
    success?: boolean;
    outcome?: FlatpakOverrideOutcome;
    operation?: FlatpakOverrideOperation;
    warning?: string | null;
    message?: string | null;
    error?: string | null;
  },
  TRefresh extends { success?: boolean },
  TApp extends Partial<FlatpakObservedState> & {
    app_id: string;
    status_available?: boolean;
    ownership_status?: FlatpakOwnershipStatus;
    ownership_operation?: FlatpakOverrideOperation;
  },
>(
  execution: Partial<FlatpakMutationExecution<TMutation, TRefresh, TApp>>,
  appId: string,
): FlatpakMutationPresentation & {
  detail: string;
  refreshTrusted: boolean;
  targetVerified: boolean;
};

export function describeFlatpakAppActions(app: Partial<FlatpakObservedState> & {
  status_available?: boolean;
  actionsDisabled?: boolean;
  ownership_status?: FlatpakOwnershipStatus;
  ownership_operation?: FlatpakOverrideOperation;
}): {
  status: "prepared" | "partial" | "pending" | "blocked" | "unknown" | "retained" | "none" | "unavailable";
  toggle?: FlatpakOverrideOperation;
  explicit: FlatpakOverrideOperation[];
};

export function createFlatpakMutationQueue(): {
  run<TMutation, TRefresh, TApp>(
    arguments_: FlatpakMutationArguments<TMutation, TRefresh, TApp>,
  ): Promise<FlatpakMutationExecution<TMutation, TRefresh, TApp>>;
};
