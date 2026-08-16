import type { RecoveryMetadata } from "../api/lsfgApi";

export type RecoveryStateName =
  | "available"
  | "busy"
  | "blocked"
  | "cleanup-pending"
  | "invalid-config";

export interface RecoveryState {
  state: RecoveryStateName;
  available: boolean;
  mutationsDisabled: boolean;
  warningVisible: boolean;
  trustedInstalled?: boolean;
  recoveryAction: NonNullable<RecoveryMetadata["recovery_action"]>;
  errorCode?: RecoveryMetadata["error_code"];
  retryable: boolean;
  recoveryPending: boolean;
  warning?: string;
}

export interface MutationBarrier {
  isBlocked(): boolean;
  tryBlock(): boolean;
  block(): void;
  release(): void;
}

export interface RecoveryStateSummary {
  mutationsDisabled: boolean;
  warningVisible: boolean;
  warning?: string;
  recoveryPending: boolean;
  refreshable: boolean;
}

export function createMutationBarrier(initiallyBlocked?: boolean): MutationBarrier;

export function mapRecoveryState(
  response?: RecoveryMetadata & { installed?: boolean; success?: boolean; error?: string },
): RecoveryState;

export function summarizeContentRecoveryStates(
  installationState: RecoveryState,
  configState: RecoveryState,
  profileState: RecoveryState,
  profileComponentState: RecoveryState,
  profileComponentMounted: boolean,
): RecoveryStateSummary;

export function refreshRecoveryStates(
  ...refreshers: Array<(() => Promise<unknown>) | null | undefined>
): Promise<void>;
