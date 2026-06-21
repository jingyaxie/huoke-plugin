export {
  CLOUD_NAV_SECTIONS,
  buildCloudRoutes,
  findCloudNavByRoute,
  getCloudRouteMeta,
  getPortalBaseUrl,
  mapH5PathToCloudRoute,
} from "./config/cloudNav";

export {
  buildPortalEmbedUrl,
  buildPortalLoginUrl,
  clearPortalAuth,
  detectNativeShell,
  getPortalDisplayName,
  handlePortalMessage,
  isPortalAuthenticated,
  isPortalEnabled,
  isPortalMessageOrigin,
  readPortalAuth,
  requiresPortalAuth,
  setPortalAuthenticated,
} from "./utils/portalShell";

export { sendPortalSmsCode, mapPortalSmsError } from "./api/portalAuth";

export {
  probePortalSession,
  submitPortalLoginForm,
  logoutPortalSession,
  syncPortalDisplayName,
} from "./utils/portalLoginBridge";

export { isLocalAcquisitionPath, LOCAL_ACQUISITION_PATHS } from "./config/authPaths";
