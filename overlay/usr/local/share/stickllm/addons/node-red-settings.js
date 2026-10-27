// StickLLM Node-RED settings. Shipped read-only in the image and mounted at
// /data/settings.js, so the editor cannot turn these back on. Flows,
// credentials and context live in vault/addons/node-red/data only.
//
// Node-RED runs any code a flow contains (function and exec nodes). In
// StickLLM it is a non-root, read-only container with no capabilities, no
// internet and no LAN (nft), reachable only through the paired gateway.
module.exports = {
  uiPort: 1880,
  flowFile: "flows.json",
  // Credentials are encrypted with a key Node-RED generates and stores in
  // /data/.config.runtime.json (vault).
  flowFilePretty: true,
  userDir: "/data",
  // No palette manager: no npm installs from the editor.
  editorTheme: {
    palette: { editable: false },
    projects: { enabled: false },
    tours: false,
  },
  externalModules: {
    autoInstall: false,
    palette: { allowInstall: false, allowUpload: false },
    modules: { allowInstall: false },
  },
  functionExternalModules: false,
  functionGlobalContext: {},
  exportGlobalContextKeys: false,
  diagnostics: { enabled: false, ui: false },
  telemetry: { enabled: false },
  runtimeState: { enabled: false, ui: false },
  logging: { console: { level: "warn", metrics: false, audit: false } },
  contextStorage: { default: { module: "memory" } },
};
