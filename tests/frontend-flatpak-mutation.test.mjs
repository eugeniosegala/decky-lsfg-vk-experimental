import assert from "node:assert/strict";
import test from "node:test";


const helper = () => import("../src/utils/flatpakMutation.js");

const complete = {
  success: true,
  outcome: "complete",
  status_available: true,
  error_code: undefined,
  operation: "remove",
};

const partial = {
  success: false,
  outcome: "partial",
  status_available: true,
  error_code: "partial_failure",
};

const availableApp = (app_id, values = {}) => ({
  app_id,
  app_name: app_id,
  wrapper_path: "/wrapper",
  status_available: true,
  config_filesystem: false,
  dll_filesystem: false,
  wrapper_filesystem: false,
  config_filesystem_ready: false,
  dll_filesystem_ready: false,
  wrapper_filesystem_ready: false,
  lsfg_config_env: false,
  vk_implicit_layer_path_env: false,
  vk_add_implicit_layer_path_env: false,
  ...values,
});

test("refreshes exactly once after a complete mutation", async () => {
  const { runFlatpakMutation } = await helper();
  let refreshes = 0;
  const refreshed = { success: true, apps: [availableApp("one")] };
  const result = await runFlatpakMutation({
    mutate: async () => complete,
    refresh: async () => { refreshes += 1; return refreshed; },
  });
  assert.equal(refreshes, 1);
  assert.equal(result.mutation, complete);
  assert.equal(result.refresh, refreshed);
});

test("refreshes exactly once after a partial mutation result", async () => {
  const { runFlatpakMutation } = await helper();
  let refreshes = 0;
  const result = await runFlatpakMutation({
    mutate: async () => partial,
    refresh: async () => { refreshes += 1; return { success: true, apps: [] }; },
  });
  assert.equal(refreshes, 1);
  assert.equal(result.mutation.error_code, "partial_failure");
});

test("refreshes exactly once after an ordinary failed mutation result", async () => {
  const { runFlatpakMutation } = await helper();
  let refreshes = 0;
  const failed = {
    success: false,
    outcome: "failed",
    status_available: true,
    error_code: "operation_failed",
  };
  const result = await runFlatpakMutation({
    mutate: async () => failed,
    refresh: async () => { refreshes += 1; return { success: true, apps: [] }; },
  });
  assert.equal(refreshes, 1);
  assert.equal(result.mutation.error_code, "operation_failed");
});

test("refreshes exactly once when the mutation RPC throws", async () => {
  const { runFlatpakMutation } = await helper();
  let refreshes = 0;
  const result = await runFlatpakMutation({
    mutate: async () => { throw new Error("RPC disconnected"); },
    refresh: async () => { refreshes += 1; return { success: true, apps: [] }; },
  });
  assert.equal(refreshes, 1);
  assert.match(result.mutationError.message, /RPC disconnected/);
});

test("surfaces refresh failure separately and retains previous authoritative apps", async () => {
  const { runFlatpakMutation } = await helper();
  const previousApps = [availableApp("one", { wrapper_filesystem: true })];
  const result = await runFlatpakMutation({
    mutate: async () => complete,
    refresh: async () => { throw new Error("list failed"); },
    previousApps,
  });
  assert.match(result.refreshError.message, /list failed/);
  assert.strictEqual(result.apps, previousApps);
});

test("never presents partial failed or unverified outcomes as success", async () => {
  const { presentFlatpakMutation } = await helper();
  for (const result of [
    partial,
    { success: false, outcome: "failed", error_code: "operation_failed" },
    { success: false, outcome: "unverified", error_code: "status_unavailable" },
  ]) {
    assert.equal(presentFlatpakMutation(result).kind, "error");
  }
  assert.equal(presentFlatpakMutation(complete).kind, "success");
  assert.equal(presentFlatpakMutation(partial).messageKey, "FLATPAK_STATUS_PARTIAL");
});

test("complete mutation is not presented as success when target refresh is unavailable", async () => {
  const { presentFlatpakMutationExecution } = await helper();
  const presentation = presentFlatpakMutationExecution({
    mutation: complete,
    refresh: { success: true },
    apps: [{ app_id: "one", status_available: false }],
  }, "one");

  assert.equal(presentation.kind, "error");
  assert.equal(presentation.messageKey, "FLATPAK_STATUS_UNAVAILABLE");
  assert.equal(presentation.refreshTrusted, false);
});

test("complete mutation is success only when refreshed state matches its target", async () => {
  const { presentFlatpakMutationExecution } = await helper();
  const presentation = presentFlatpakMutationExecution({
    mutation: { ...complete, operation: "set" },
    refresh: { success: true },
    apps: [availableApp("one", {
      config_filesystem: true,
      dll_filesystem: true,
      wrapper_filesystem: true,
      config_filesystem_ready: true,
      dll_filesystem_ready: true,
      wrapper_filesystem_ready: true,
    })],
  }, "one");

  assert.equal(presentation.kind, "success");
  assert.equal(presentation.refreshTrusted, true);
  assert.equal(presentation.targetVerified, true);
});

test("complete mutation is not presented as success when list refresh fails", async () => {
  const { presentFlatpakMutationExecution } = await helper();
  const presentation = presentFlatpakMutationExecution({
    mutation: complete,
    refresh: { success: false },
    refreshMessage: "enumeration failed",
    apps: [availableApp("one")],
  }, "one");

  assert.equal(presentation.kind, "error");
  assert.equal(presentation.messageKey, "FLATPAK_STATUS_UNAVAILABLE");
  assert.equal(presentation.detail, "enumeration failed");
});

test("complete mutation is not success when a concurrent change reverses its target", async () => {
  const { presentFlatpakMutationExecution } = await helper();
  const presentation = presentFlatpakMutationExecution({
    mutation: { ...complete, operation: "set" },
    refresh: { success: true },
    apps: [availableApp("one")],
  }, "one");

  assert.equal(presentation.kind, "error");
  assert.equal(presentation.messageKey, "FLATPAK_APPLICATION_ACTION_FAILED");
  assert.equal(presentation.refreshTrusted, true);
  assert.equal(presentation.targetVerified, false);
  assert.match(presentation.detail, /no longer matches/);
});

test("frontend diagnostics are single-line and bounded", async () => {
  const { boundedFlatpakDetail } = await helper();
  const detail = boundedFlatpakDetail("secret\0\n\t\u202e" + "x".repeat(5000));
  assert.equal(detail.length, 512);
  assert.equal(/[\x00-\x1F\x7F]/.test(detail), false);
  assert.equal(detail.includes("\u202e"), false);
});

test("an unavailable app retains prior trusted booleans only as stale display data", async () => {
  const { mergeFlatpakApps } = await helper();
  const previous = [availableApp("one", {
    config_filesystem: true,
    dll_filesystem: true,
    wrapper_filesystem: true,
  })];
  const unavailable = {
    app_id: "one",
    app_name: "one renamed",
    wrapper_path: "/wrapper",
    status_available: false,
    status_error_code: "status_unavailable",
  };
  const merged = mergeFlatpakApps(previous, { success: true, apps: [unavailable] });
  assert.equal(merged.apps[0].status_available, false);
  assert.equal(merged.apps[0].stale, true);
  assert.equal(merged.apps[0].stale_state.wrapper_filesystem, true);
  assert.equal(merged.apps[0].actionsDisabled, true);
  assert.equal(merged.apps[0].wrapper_filesystem, undefined);
});

test("a newly discovered unavailable app has no false toggle state or actions", async () => {
  const { mergeFlatpakApps } = await helper();
  const unavailable = {
    app_id: "new",
    app_name: "new",
    wrapper_path: "/wrapper",
    status_available: false,
    status_error_code: "status_unavailable",
  };
  const merged = mergeFlatpakApps([], { success: true, apps: [unavailable] });
  assert.equal(merged.apps[0].stale_state, undefined);
  assert.equal(merged.apps[0].wrapper_filesystem, undefined);
  assert.equal(merged.apps[0].actionsDisabled, true);
});

test("a list-level failure retains the prior list and disables mutations", async () => {
  const { mergeFlatpakApps } = await helper();
  const previous = [availableApp("one")];
  const merged = mergeFlatpakApps(previous, { success: false, error: "enumeration failed" });
  assert.strictEqual(merged.apps, previous);
  assert.equal(merged.mutationsDisabled, true);
  assert.equal(merged.error, "enumeration failed");
});

test("a list-level failure exposes only bounded sanitized diagnostic text", async () => {
  const { mergeFlatpakApps } = await helper();
  const merged = mergeFlatpakApps([], {
    success: false,
    error: "enumeration failed\u202e\n" + "x".repeat(5000),
  });
  assert.equal(merged.error.length, 512);
  assert.equal(merged.error.includes("\u202e"), false);
  assert.equal(merged.error.includes("\n"), false);
});

test("partial state exposes explicit finish and remove actions instead of a toggle", async () => {
  const { describeFlatpakAppActions } = await helper();
  const app = availableApp("one", { config_filesystem: true });
  const actions = describeFlatpakAppActions(app);
  assert.equal(actions.toggle, undefined);
  assert.deepEqual(actions.explicit, ["set", "remove"]);
});

test("serializes a second mutation until the first mutation and refresh finish", async () => {
  const { createFlatpakMutationQueue } = await helper();
  const events = [];
  let releaseFirstRefresh;
  const firstRefreshGate = new Promise((resolve) => { releaseFirstRefresh = resolve; });
  const queue = createFlatpakMutationQueue();

  const first = queue.run({
    mutate: async () => { events.push("mutate-one"); return complete; },
    refresh: async () => {
      events.push("refresh-one-start");
      await firstRefreshGate;
      events.push("refresh-one-end");
      return { success: true, apps: [] };
    },
  });
  const second = queue.run({
    mutate: async () => { events.push("mutate-two"); return complete; },
    refresh: async () => { events.push("refresh-two"); return { success: true, apps: [] }; },
  });

  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(events, ["mutate-one", "refresh-one-start"]);
  releaseFirstRefresh();
  await Promise.all([first, second]);
  assert.deepEqual(events, [
    "mutate-one", "refresh-one-start", "refresh-one-end", "mutate-two", "refresh-two",
  ]);
});

test("uses the refreshed serialized state rather than the mutation response as app truth", async () => {
  const { createFlatpakMutationQueue } = await helper();
  const authoritative = availableApp("one", { wrapper_filesystem: true });
  const result = await createFlatpakMutationQueue().run({
    mutate: async () => ({ ...partial, observed_state: {
      config_filesystem: false,
      dll_filesystem: false,
      wrapper_filesystem: false,
      lsfg_config_env: false,
      vk_implicit_layer_path_env: false,
      vk_add_implicit_layer_path_env: false,
    } }),
    refresh: async () => ({ success: true, apps: [authoritative] }),
    previousApps: [],
  });
  assert.deepEqual(result.apps, [authoritative]);
  assert.equal(result.mutation.outcome, "partial");
});
