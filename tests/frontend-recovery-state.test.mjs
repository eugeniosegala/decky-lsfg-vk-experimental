import assert from "node:assert/strict";
import test from "node:test";

import {
  createLatestRequestGate,
  createMutationBarrier,
  mapRecoveryState,
  refreshRecoveryStates,
  summarizeContentRecoveryStates,
  transientRefreshRecoveryState,
} from "../src/utils/recoveryState.js";


const rows = [
  {
    name: "old backend response remains available",
    response: { installed: false },
    expected: ["available", true, false, false],
  },
  {
    name: "explicit availability wins over additive metadata",
    response: { status_available: true, warning: "informational" },
    expected: ["available", true, false, true],
  },
  {
    name: "missing availability with busy metadata fails safe",
    response: { error_code: "mutation_busy", retryable: true },
    expected: ["busy", false, true, true],
  },
  {
    name: "explicit unavailable busy status ignores installed sentinel",
    response: {
      status_available: false,
      installed: true,
      error_code: "mutation_busy",
      retryable: true,
      recovery_pending: false,
      warning: "refresh status",
      recovery_action: "refresh",
    },
    expected: ["busy", false, true, true],
  },
  {
    name: "blocked recovery requires repair",
    response: {
      status_available: false,
      error_code: "recovery_blocked",
      retryable: false,
      recovery_pending: true,
      warning: "repair required",
      recovery_action: "repair_required",
    },
    expected: ["blocked", false, true, true],
  },
  {
    name: "valid journal maps to cleanup pending without mutation retry",
    response: {
      status_available: false,
      error_code: "recovery_pending",
      retryable: false,
      recovery_pending: true,
      warning: "wait for recovery",
      recovery_action: "wait_for_recovery",
    },
    expected: ["cleanup-pending", false, true, true],
  },
  {
    name: "malformed persisted config remains visibly invalid",
    response: {
      status_available: true,
      success: true,
      error_code: "invalid_persisted_state",
      retryable: false,
      recovery_pending: false,
      warning: "defaults are shown",
      recovery_action: "repair_required",
    },
    expected: ["invalid-config", true, true, true],
  },
];

for (const { name, response, expected } of rows) {
  test(name, () => {
    const mapped = mapRecoveryState(response);

    assert.deepEqual(
      [mapped.state, mapped.available, mapped.mutationsDisabled, mapped.warningVisible],
      expected,
    );
  });
}

test("missing availability with any recovery metadata is unavailable", () => {
  for (const response of [
    { error_code: "durability_failure" },
    { recovery_pending: false },
    { recovery_action: "none" },
    { warning: "partial backend response" },
  ]) {
    assert.equal(mapRecoveryState(response).available, false);
  }
});

test("metadata-free legacy failures fail closed", () => {
  for (const response of [
    { success: false },
    { success: false, error: "" },
    { error: "legacy read failed" },
    { success: true, error: "contradictory legacy failure" },
  ]) {
    const mapped = mapRecoveryState(response);
    assert.equal(mapped.available, false);
    assert.equal(mapped.mutationsDisabled, true);
    assert.equal(mapped.warningVisible, true);
  }
});

test("metadata-free legacy successes remain available", () => {
  for (const response of [
    { installed: false },
    { success: true },
    { success: true, error: "" },
  ]) {
    const mapped = mapRecoveryState(response);
    assert.equal(mapped.available, true);
    assert.equal(mapped.mutationsDisabled, false);
  }
});

test("an unmounted profile component cannot block a fresh install", () => {
  const available = mapRecoveryState({ status_available: true, installed: false });
  const staleUnmountedComponent = mapRecoveryState({
    status_available: false,
    error_code: "refresh_required",
  });

  const summary = summarizeContentRecoveryStates(
    available,
    available,
    available,
    staleUnmountedComponent,
    false,
  );

  assert.equal(staleUnmountedComponent.mutationsDisabled, true);
  assert.equal(summary.mutationsDisabled, false);
  assert.equal(summary.warningVisible, false);
});

test("an active profile component recovery state still blocks mutations", () => {
  const available = mapRecoveryState({ status_available: true });
  const cleanupPending = mapRecoveryState({
    status_available: false,
    error_code: "recovery_pending",
    recovery_pending: true,
    recovery_action: "wait_for_recovery",
  });

  const summary = summarizeContentRecoveryStates(
    available,
    available,
    available,
    cleanupPending,
    true,
  );

  assert.equal(summary.mutationsDisabled, true);
  assert.equal(summary.warningVisible, true);
  assert.equal(summary.recoveryPending, true);
});

test("blocked recovery evidence does not expose a futile cleanup retry", () => {
  const available = mapRecoveryState({ status_available: true });
  const blocked = mapRecoveryState({
    status_available: false,
    error_code: "recovery_blocked",
    recovery_pending: true,
    recovery_action: "repair_required",
  });

  const summary = summarizeContentRecoveryStates(
    blocked,
    available,
    available,
    available,
    false,
  );

  assert.equal(summary.mutationsDisabled, true);
  assert.equal(summary.warningVisible, true);
  assert.equal(summary.recoveryPending, false);
  assert.equal(summary.refreshable, false);
});

test("transient busy state exposes a safe status refresh", () => {
  const available = mapRecoveryState({ status_available: true });
  const busy = mapRecoveryState({
    status_available: false,
    error_code: "mutation_busy",
    retryable: true,
    recovery_pending: false,
    recovery_action: "refresh",
  });

  const summary = summarizeContentRecoveryStates(
    busy,
    available,
    available,
    available,
    false,
  );

  assert.equal(summary.mutationsDisabled, true);
  assert.equal(summary.recoveryPending, false);
  assert.equal(summary.refreshable, true);
});

test("an exception fallback fails closed but remains refreshable", () => {
  const available = mapRecoveryState({ status_available: true });
  const transientFailure = transientRefreshRecoveryState();

  const summary = summarizeContentRecoveryStates(
    transientFailure,
    available,
    available,
    available,
    false,
  );

  assert.equal(transientFailure.available, false);
  assert.equal(transientFailure.mutationsDisabled, true);
  assert.equal(transientFailure.retryable, true);
  assert.equal(transientFailure.recoveryAction, "refresh");
  assert.equal(summary.refreshable, true);
});

test("latest request gate ignores a delayed older success", async () => {
  const gate = createLatestRequestGate();
  const published = [];
  let resolveOlder;
  let resolveNewer;
  const olderResponse = new Promise((resolve) => { resolveOlder = resolve; });
  const newerResponse = new Promise((resolve) => { resolveNewer = resolve; });

  const load = async (response) => {
    const requestId = gate.begin();
    const value = await response;
    if (gate.isLatest(requestId)) published.push(value);
  };

  const olderLoad = load(olderResponse);
  const newerLoad = load(newerResponse);
  resolveNewer("new truth");
  await newerLoad;
  resolveOlder("stale truth");
  await olderLoad;

  assert.deepEqual(published, ["new truth"]);
});

test("latest request gate ignores a delayed older exception", async () => {
  const gate = createLatestRequestGate();
  const published = [];
  let rejectOlder;
  let resolveNewer;
  const olderResponse = new Promise((_, reject) => { rejectOlder = reject; });
  const newerResponse = new Promise((resolve) => { resolveNewer = resolve; });

  const load = async (response) => {
    const requestId = gate.begin();
    try {
      const value = await response;
      if (gate.isLatest(requestId)) published.push(value);
    } catch {
      if (gate.isLatest(requestId)) published.push("transient failure");
    }
  };

  const olderLoad = load(olderResponse);
  const newerLoad = load(newerResponse);
  resolveNewer("new truth");
  await newerLoad;
  rejectOlder(new Error("stale failure"));
  await olderLoad;

  assert.deepEqual(published, ["new truth"]);
});

test("starting a mutation invalidates a read that is still in flight", async () => {
  const gate = createLatestRequestGate();
  const published = [];
  let resolveRead;
  const response = new Promise((resolve) => { resolveRead = resolve; });

  const load = async () => {
    const requestId = gate.begin();
    const value = await response;
    if (gate.isLatest(requestId)) published.push(value);
  };

  const pendingRead = load();
  gate.begin(); // Mutation starts and invalidates pre-mutation read evidence.
  resolveRead("pre-mutation truth");
  await pendingRead;

  assert.deepEqual(published, []);
});

test("status refresh reruns every active source including the mounted profile component", async () => {
  const calls = [];
  const refresher = (name) => async () => {
    calls.push(name);
  };

  await refreshRecoveryStates(
    refresher("installation"),
    refresher("profiles-hook"),
    refresher("configuration"),
    refresher("profiles-component"),
    undefined,
  );

  assert.deepEqual(calls.sort(), [
    "configuration",
    "installation",
    "profiles-component",
    "profiles-hook",
  ]);
});

test("cleanup pending never enables or recommends retrying a mutation", () => {
  const mapped = mapRecoveryState({
    status_available: false,
    error_code: "recovery_pending",
    retryable: false,
    recovery_pending: true,
    warning: "cleanup pending",
    recovery_action: "wait_for_recovery",
  });

  assert.equal(mapped.mutationsDisabled, true);
  assert.notEqual(mapped.recoveryAction, "retry");
});

test("unavailable installed sentinel cannot render as installed or not installed", () => {
  const mapped = mapRecoveryState({
    status_available: false,
    installed: true,
    error_code: "recovery_pending",
    recovery_pending: true,
    warning: "state unavailable",
    recovery_action: "wait_for_recovery",
  });

  assert.equal(mapped.available, false);
  assert.equal(mapped.trustedInstalled, undefined);
  assert.equal(mapped.warningVisible, true);
});

test("refresh-required response closes the mutation path", () => {
  const mapped = mapRecoveryState({
    success: false,
    error_code: "refresh_required",
    recovery_action: "refresh",
  });

  assert.equal(mapped.available, false);
  assert.equal(mapped.mutationsDisabled, true);
  assert.equal(mapped.recoveryAction, "refresh");
});

test("mutation barrier rejects a second mutation until a fresh read releases it", () => {
  const barrier = createMutationBarrier(true);
  assert.equal(barrier.isBlocked(), true);

  barrier.release();
  assert.equal(barrier.isBlocked(), false);

  // The first mutation closes the gate synchronously, before its RPC awaits.
  assert.equal(barrier.tryBlock(), true);
  assert.equal(barrier.tryBlock(), false);
  assert.equal(barrier.isBlocked(), true);

  // A completed mutation response does not reopen the gate. Only the
  // authoritative follow-up read may do that.
  barrier.release();
  assert.equal(barrier.isBlocked(), false);
});
