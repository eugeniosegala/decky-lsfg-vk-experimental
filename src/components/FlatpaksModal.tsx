import { FC, useState, useEffect, useRef, CSSProperties } from 'react';
import {
  ModalRoot,
  DialogBody,
  DialogHeader,
  DialogControlsSection,
  DialogControlsSectionHeader,
  ButtonItem,
  PanelSectionRow,
  Field,
  Toggle,
  Spinner,
  Focusable,
  showModal,
  ConfirmModal
} from '@decky/ui';
import { FaCheck, FaTimes, FaDownload, FaTrash, FaCog } from 'react-icons/fa';
import { 
  checkFlatpakExtensionStatus, 
  installFlatpakExtension, 
  uninstallFlatpakExtension,
  getFlatpakApps,
  setFlatpakAppOverride,
  removeFlatpakAppOverride,
  FlatpakExtensionStatus,
  FlatpakApp,
  FlatpakAppInfo,
  FlatpakOverrideOperation,
  FlatpakOverrideResult
} from '../api/lsfgApi';
import t from '../i18n/i18n';
import { showErrorToast, showSuccessToast } from '../utils/toastUtils';
import {
  boundedFlatpakDetail,
  createFlatpakMutationQueue,
  describeFlatpakAppActions,
  mergeFlatpakApps,
  presentFlatpakMutationExecution,
  FlatpakDisplayApp,
} from '../utils/flatpakMutation.js';

interface FlatpaksModalProps {
  closeModal?: () => void;
}

type FlatpakDisplayInfo = Omit<FlatpakAppInfo, 'apps'> & {
  apps: FlatpakDisplayApp<FlatpakApp>[];
};

const flatpakPresentationText = (messageKey: string): string => {
  switch (messageKey) {
    case 'FLATPAK_APPLICATION_UPDATED':
      return t('FLATPAK_APPLICATION_UPDATED', 'Flatpak application updated');
    case 'FLATPAK_APPLICATION_VERIFIED_WITH_WARNING':
      return t('FLATPAK_APPLICATION_VERIFIED_WITH_WARNING', 'Flatpak state verified with a warning');
    case 'FLATPAK_STATUS_PARTIAL':
      return t('FLATPAK_STATUS_PARTIAL', 'Partial');
    case 'FLATPAK_STATUS_UNAVAILABLE':
      return t('FLATPAK_STATUS_UNAVAILABLE', 'Status unavailable');
    case 'FLATPAK_PRECONDITION_FAILED':
      return t('FLATPAK_PRECONDITION_FAILED', 'Required setup is not ready');
    default:
      return t('FLATPAK_APPLICATION_ACTION_FAILED', 'Could not update');
  }
};

export const FlatpaksModal: FC<FlatpaksModalProps> = ({ closeModal }) => {
  const [extensionStatus, setExtensionStatus] = useState<FlatpakExtensionStatus | null>(null);
  const [flatpakApps, setFlatpakApps] = useState<FlatpakDisplayInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [operationInProgress, setOperationInProgress] = useState<string | null>(null);
  const [appErrors, setAppErrors] = useState<Record<string, string>>({});
  const [appWarnings, setAppWarnings] = useState<Record<string, string>>({});
  const [appMutationsDisabled, setAppMutationsDisabled] = useState(true);
  const [appListError, setAppListError] = useState<string | null>(null);
  const flatpakAppsRef = useRef<FlatpakDisplayInfo | null>(null);
  const mutationActiveRef = useRef(false);
  const appMutationQueue = useRef(createFlatpakMutationQueue());

  const applyFlatpakAppsResult = (result: FlatpakAppInfo) => {
    const previousApps = flatpakAppsRef.current?.apps ?? [];
    const merged = mergeFlatpakApps(previousApps, result);
    setAppMutationsDisabled(merged.mutationsDisabled);
    setAppListError(merged.error ?? null);

    const next = result.success
      ? { ...result, apps: merged.apps }
      : flatpakAppsRef.current ?? { ...result, apps: merged.apps };
    if (result.success) {
      setAppErrors({});
      setAppWarnings({});
    }
    flatpakAppsRef.current = next;
    setFlatpakApps(next);
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [statusResult, appsResult] = await Promise.all([
        checkFlatpakExtensionStatus(),
        getFlatpakApps()
      ]);

      setExtensionStatus(statusResult);
      applyFlatpakAppsResult(appsResult);
    } catch (error) {
      console.error('Error loading Flatpak data:', error);
      setAppMutationsDisabled(true);
      setAppListError(boundedFlatpakDetail(error) || t('FLATPAK_ERROR_APPS', 'Failed to load Flatpak applications'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleExtensionOperation = async (operation: 'install' | 'uninstall', version: string) => {
    if (mutationActiveRef.current) return;
    mutationActiveRef.current = true;
    const operationId = `${operation}-${version}`;
    setOperationInProgress(operationId);

    try {
      const result = operation === 'install' 
        ? await installFlatpakExtension(version)
        : await uninstallFlatpakExtension(version);

      if (result.success) {
        // Reload status after operation
        const newStatus = await checkFlatpakExtensionStatus();
        setExtensionStatus(newStatus);
        showSuccessToast(t('FLATPAK_EXTENSION_UPDATED', 'Flatpak extension updated'), result.message || `${version} ${t('FLATPAK_RUNTIME_EXTENSION_UPDATED', 'runtime extension updated')}`);
      } else {
        const action = operation === 'install'
          ? t('FLATPAK_INSTALL_ACTION', 'install')
          : t('FLATPAK_UNINSTALL_ACTION', 'uninstall');
        showErrorToast(t('FLATPAK_EXTENSION_FAILED', 'Flatpak extension failed'), result.error || result.message || `${t('FLATPAK_EXTENSION_ACTION_FAILED', 'Could not')} ${action} ${version} ${t('FLATPAK_RUNTIME_EXTENSION', 'runtime extension')}`);
      }
    } catch (error) {
      console.error(`Error ${operation}ing extension:`, error);
      showErrorToast(t('FLATPAK_EXTENSION_FAILED', 'Flatpak extension failed'), String(error));
    } finally {
      mutationActiveRef.current = false;
      setOperationInProgress(null);
    }
  };

  const handleAppOverrideOperation = async (
    app: FlatpakDisplayApp<FlatpakApp>,
    operation: FlatpakOverrideOperation,
  ) => {
    if (mutationActiveRef.current || appMutationsDisabled || app.status_available !== true) return;
    mutationActiveRef.current = true;
    const operationId = `app-${app.app_id}`;
    setOperationInProgress(operationId);
    setAppErrors((current) => {
      const next = { ...current };
      delete next[app.app_id];
      return next;
    });
    setAppWarnings((current) => {
      const next = { ...current };
      delete next[app.app_id];
      return next;
    });

    try {
      const execution = await appMutationQueue.current.run<FlatpakOverrideResult, FlatpakAppInfo, FlatpakApp>({
        mutate: () => operation === 'set'
          ? setFlatpakAppOverride(app.app_id)
          : removeFlatpakAppOverride(app.app_id),
        refresh: getFlatpakApps,
        previousApps: flatpakAppsRef.current?.apps ?? [],
      });

      if (execution.refresh) {
        applyFlatpakAppsResult(execution.refresh);
      } else {
        setAppMutationsDisabled(true);
        setAppListError(
          boundedFlatpakDetail(execution.refreshError)
          || t('FLATPAK_ERROR_APPS', 'Failed to load Flatpak applications'),
        );
      }

      const presentation = presentFlatpakMutationExecution(execution, app.app_id);

      if (presentation.kind === 'success') {
        if (execution.mutation?.warning && presentation.detail) {
          setAppWarnings((current) => ({
            ...current,
            [app.app_id]: presentation.detail,
          }));
        }
        showSuccessToast(
          flatpakPresentationText(presentation.messageKey),
          presentation.detail || `${app.app_name || app.app_id} ${t('FLATPAK_UPDATED', 'updated')}`,
        );
      } else {
        const summary = flatpakPresentationText(presentation.messageKey);
        setAppErrors((current) => ({
          ...current,
          [app.app_id]: presentation.detail ? `${summary}: ${presentation.detail}` : summary,
        }));
      }
    } catch (error) {
      console.error('Error changing app override:', error);
      const detail = boundedFlatpakDetail(error);
      setAppErrors((current) => ({
        ...current,
        [app.app_id]: detail || t('FLATPAK_APPLICATION_ACTION_FAILED', 'Could not update'),
      }));
      setAppMutationsDisabled(true);
    } finally {
      mutationActiveRef.current = false;
      setOperationInProgress(null);
    }
  };

  const confirmOperation = (operation: () => void, title: string, description: string) => {
    showModal(
      <ConfirmModal
        strTitle={title}
        strDescription={description}
        onOK={operation}
        onCancel={() => {}}
      />
    );
  };

  const handleRuntimePrimaryAction = (version: string, installed: boolean) => {
    const operation: 'install' | 'uninstall' = installed ? 'uninstall' : 'install';
    const action = () => handleExtensionOperation(operation, version);

    if (operation === 'uninstall') {
      confirmOperation(
        action,
        t('FLATPAK_UNINSTALL_TITLE', 'Uninstall Runtime Extension'),
        `${t('FLATPAK_UNINSTALL_CONFIRM_PREFIX', 'Are you sure you want to uninstall the')} ${version} ${t('FLATPAK_UNINSTALL_CONFIRM_SUFFIX', 'runtime extension?')}`
      );
      return;
    }

    action();
  };

  if (loading) {
    return (
      <ModalRoot closeModal={closeModal}>
        <DialogHeader>{t('FLATPAK_MODAL_TITLE', 'Flatpak Extensions')}</DialogHeader>
        <DialogBody>
          <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}>
            <Spinner />
          </div>
        </DialogBody>
      </ModalRoot>
    );
  }

  const instructionSteps = [
    {
      id: 'try-first',
      title: t('FLATPAK_STEP_TRY_FIRST', 'Try first:'),
      command: '~/.local/bin/lsfg-vk-experimental'
    },
    {
      id: 'try-full-path',
      title: t('FLATPAK_STEP_TRY_FULL_PATH', "If that doesn't work, try full path:"),
      command: '/home/(username)/.local/bin/lsfg-vk-experimental'
    },
    {
      id: 'final-result',
      title: t('FLATPAK_STEP_FINAL', 'Final result should look like:'),
      command: '~/.local/bin/lsfg-vk-experimental "usr/bin/flatpak"'
    }
  ];

  const focusableInstructionStyle: CSSProperties = {
    padding: '10px',
    background: 'rgba(0, 0, 0, 0.3)',
    borderRadius: '6px',
    marginBottom: '12px'
  };

  const commandStyle: CSSProperties = {
    fontFamily: 'monospace',
    fontSize: '0.85em',
    background: 'rgba(0, 0, 0, 0.45)',
    padding: '8px',
    borderRadius: '4px',
    marginTop: '6px'
  };

  return (
    <ModalRoot closeModal={closeModal}>
      <DialogHeader>{t('FLATPAK_MODAL_TITLE', 'Flatpak Extensions')}</DialogHeader>
      <DialogBody>
        <Focusable flow-children="vertical">
          {/* Extension Status Section */}
          <DialogControlsSection>
            <DialogControlsSectionHeader>{t('FLATPAK_RUNTIME_INSTALLER', 'Runtime Extension Installer')}</DialogControlsSectionHeader>

            {extensionStatus && extensionStatus.success ? (
              <>
                {[
                  { version: '23.08', label: t('FLATPAK_RUNTIME_23', 'Runtime 23.08'), installed: extensionStatus.installed_23_08 },
                  { version: '24.08', label: t('FLATPAK_RUNTIME_24', 'Runtime 24.08'), installed: extensionStatus.installed_24_08 },
                  { version: '25.08', label: t('FLATPAK_RUNTIME_25', 'Runtime 25.08'), installed: extensionStatus.installed_25_08 }
                ].map((runtime) => {
                  const isBusy = operationInProgress === `install-${runtime.version}` || operationInProgress === `uninstall-${runtime.version}`;

                  return (
                    <div key={runtime.version}>
                      <PanelSectionRow>
                        <Field
                          label={runtime.label}
                          description={runtime.installed ? t('FLATPAK_INSTALLED', 'Installed') : t('FLATPAK_NOT_INSTALLED', 'Not installed')}
                          icon={runtime.installed ? <FaCheck style={{ color: 'green' }} /> : <FaTimes style={{ color: 'red' }} />}
                        />
                      </PanelSectionRow>
                      <PanelSectionRow>
                        <ButtonItem
                          layout="below"
                          onClick={() => handleRuntimePrimaryAction(runtime.version, runtime.installed)}
                          disabled={operationInProgress !== null}
                        >
                          {isBusy ? <Spinner /> : runtime.installed ? <><FaTrash /> {t('FLATPAK_UNINSTALL_BTN', 'Uninstall')}</> : <><FaDownload /> {t('FLATPAK_INSTALL_BTN', 'Install')}</>}
                        </ButtonItem>
                      </PanelSectionRow>
                      {runtime.installed && (
                        <PanelSectionRow>
                          <ButtonItem
                            layout="below"
                            onClick={() => handleExtensionOperation('install', runtime.version)}
                            disabled={operationInProgress !== null}
                          >
                            {operationInProgress === `install-${runtime.version}` ? <Spinner /> : <><FaDownload /> {t('FLATPAK_UPDATE_BTN', 'Update')}</>}
                          </ButtonItem>
                        </PanelSectionRow>
                      )}
                    </div>
                  );
                })}
              </>
            ) : (
              <PanelSectionRow>
                <Field 
                  label={t('FLATPAK_ERROR', 'Error')}
                  description={extensionStatus?.error || t('FLATPAK_ERROR_STATUS', 'Failed to check extension status')}
                  icon={<FaTimes style={{color: 'red'}} />}
                />
              </PanelSectionRow>
            )}
          </DialogControlsSection>

          {/* Flatpak Apps Section */}
          <DialogControlsSection>
            <DialogControlsSectionHeader>{t('FLATPAK_APPS_TITLE', 'Flatpak Applications')}</DialogControlsSectionHeader>
            <PanelSectionRow>
              <Field
                label={t('FLATPAK_PREPARE_APPLICATION', 'Prepare an application')}
                description={t('FLATPAK_PREPARE_APPLICATION_DESC', "Install its matching runtime extension, then prepare only that app here. For Heroic, use the full Wrapper command path shown below in each game you want to enable. Preparing Heroic does not enable frame generation globally.")}
              />
            </PanelSectionRow>

            {appListError && (
              <PanelSectionRow>
                <Field
                  label={t('FLATPAK_STATUS_UNAVAILABLE', 'Status unavailable')}
                  description={appListError}
                  icon={<FaTimes style={{ color: '#f4a261' }} />}
                >
                  <ButtonItem
                    layout="below"
                    onClick={loadData}
                    disabled={operationInProgress !== null}
                  >
                    {t('FLATPAK_REFRESH_STATUS', 'Refresh status')}
                  </ButtonItem>
                </Field>
              </PanelSectionRow>
            )}

            {flatpakApps && flatpakApps.success ? (
              flatpakApps.apps.length > 0 ? (
                flatpakApps.apps.map((app) => {
                  const actions = describeFlatpakAppActions(app);
                  const hasOverrides = actions.status === 'prepared';

                  let statusColor = 'red';
                  let statusText = t('FLATPAK_STATUS_NO_OVERRIDES', 'No LSFG access');

                  if (actions.status === 'unavailable') {
                    statusColor = '#f4a261';
                    statusText = t('FLATPAK_STATUS_UNAVAILABLE', 'Status unavailable');
                  } else if (hasOverrides) {
                    statusColor = 'green';
                    statusText = t('FLATPAK_STATUS_CONFIGURED', 'Prepared');
                  } else if (actions.status === 'partial') {
                    statusColor = 'orange';
                    statusText = t('FLATPAK_STATUS_PARTIAL', 'Partial');
                  }

                  const appError = appErrors[app.app_id];
                  const appWarning = appWarnings[app.app_id];
                  const statusReason = app.status_available === false
                    ? boundedFlatpakDetail(app.status_error)
                    : '';
                  const statusDescription = statusReason
                    ? `${statusText}: ${statusReason}`
                    : statusText;

                  return (
                    <PanelSectionRow key={app.app_id}>
                      <Field 
                        label={app.app_name || app.app_id}
                        description={app.app_id === 'com.heroicgameslauncher.hgl'
                          ? t(
                            'FLATPAK_HEROIC_APP_DESC',
                            '{app_id} - {status}. Per game: Settings > Advanced > enter this in Heroic\'s first Wrapper field: {wrapper_path}; leave Arguments empty.',
                            { app_id: app.app_id, status: statusDescription, wrapper_path: app.wrapper_path }
                          )
                          : `${app.app_id} - ${statusDescription}`}
                        icon={<FaCog style={{color: appError ? '#f44336' : statusColor}} />}
                      >
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px', maxWidth: '100%' }}>
                          {appError && (
                            <div
                              style={{
                                color: '#ff9b9b',
                                fontSize: '0.82em',
                                lineHeight: '1.35',
                                maxWidth: '260px',
                                overflowWrap: 'anywhere',
                                textAlign: 'left'
                              }}
                            >
                              {appError}
                            </div>
                          )}
                          {appWarning && (
                            <div
                              style={{
                                color: '#f4a261',
                                fontSize: '0.82em',
                                lineHeight: '1.35',
                                maxWidth: '260px',
                                overflowWrap: 'anywhere',
                                textAlign: 'left'
                              }}
                            >
                              {appWarning}
                            </div>
                          )}
                          {actions.toggle && (
                            <Toggle
                              value={hasOverrides}
                              onChange={() => handleAppOverrideOperation(app, actions.toggle!)}
                              disabled={operationInProgress !== null || appMutationsDisabled}
                            />
                          )}
                          {actions.status === 'partial' && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: '220px' }}>
                              <ButtonItem
                                layout="below"
                                onClick={() => handleAppOverrideOperation(app, 'set')}
                                disabled={operationInProgress !== null || appMutationsDisabled}
                              >
                                {t('FLATPAK_FINISH_PREPARING', 'Finish preparing')}
                              </ButtonItem>
                              <ButtonItem
                                layout="below"
                                onClick={() => handleAppOverrideOperation(app, 'remove')}
                                disabled={operationInProgress !== null || appMutationsDisabled}
                              >
                                {t('FLATPAK_REMOVE_REMAINING', 'Remove remaining LSFG access')}
                              </ButtonItem>
                            </div>
                          )}
                          {actions.status === 'unavailable' && (
                            <ButtonItem
                              layout="below"
                              onClick={loadData}
                              disabled={operationInProgress !== null}
                            >
                              {t('FLATPAK_REFRESH_STATUS', 'Refresh status')}
                            </ButtonItem>
                          )}
                        </div>
                      </Field>
                    </PanelSectionRow>
                  );
                })
              ) : (
                <PanelSectionRow>
                  <Field 
                  label={t('FLATPAK_NO_APPS', 'No Flatpak Apps Found')}
                  description={t('FLATPAK_NO_APPS_DESC', 'No Flatpak applications are currently installed')}
                  />
                </PanelSectionRow>
              )
            ) : (
              <PanelSectionRow>
                <Field 
                  label={t('FLATPAK_ERROR', 'Error')}
                  description={flatpakApps?.error || t('FLATPAK_ERROR_APPS', 'Failed to load Flatpak applications')}
                  icon={<FaTimes style={{color: 'red'}} />}
                />
              </PanelSectionRow>
            )}
          </DialogControlsSection>

          {/* Steam Configuration Instructions */}
          <DialogControlsSection>
            <DialogControlsSectionHeader>{t('FLATPAK_STEAM_CONFIG_TITLE', 'Optional Steam Flatpak shortcuts')}</DialogControlsSectionHeader>
            <div
              style={{
                padding: '12px',
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '8px',
                margin: '8px 0',
                display: 'flex',
                flexDirection: 'column'
              }}
            >
              <div style={{ fontWeight: 'bold', marginBottom: '8px', color: '#fff' }}>
                {t('FLATPAK_STEAM_CONFIG_HEADER', 'Configure Steam Flatpak Shortcuts')}
              </div>
              <div style={{ fontSize: '0.9em', lineHeight: '1.4', marginBottom: '8px' }}>
                {t('FLATPAK_STEAM_CONFIG_DESC', "Only use these target instructions for a Flatpak shortcut inside Steam. Heroic users should prepare Heroic above, then set the existing experimental wrapper in the chosen game's Advanced settings.")}
              </div>
              <div style={{ fontSize: '0.9em', lineHeight: '1.4', marginBottom: '12px', color: '#ffa500' }}>
                <strong>{t('FLATPAK_IMPORTANT_LABEL', 'IMPORTANT:')}</strong> {t('FLATPAK_STEAM_CONFIG_IMPORTANT', 'Set this in TARGET (NOT LAUNCH OPTIONS)')}
              </div>

              {instructionSteps.map((step) => (
                <Focusable
                  key={step.id}
                  focusWithinClassName="gpfocuswithin"
                  onActivate={() => {}}
                  style={focusableInstructionStyle}
                >
                  <div style={{ fontWeight: 'bold' }}>{step.title}</div>
                  <div style={commandStyle}>{step.command}</div>
                </Focusable>
              ))}

            </div>
          </DialogControlsSection>

          {/* Close Button */}
          <DialogControlsSection>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={closeModal}
              >
                {t('FLATPAK_CLOSE', 'Close')}
              </ButtonItem>
            </PanelSectionRow>
          </DialogControlsSection>
        </Focusable>
      </DialogBody>
    </ModalRoot>
  );
};
