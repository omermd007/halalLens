/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STANDALONE?: string;
  readonly VITE_BASE_PATH?: string;
  readonly VITE_PROXY_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

