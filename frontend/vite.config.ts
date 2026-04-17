import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const root = path.dirname(fileURLToPath(import.meta.url));

const syncAppIconFromAssets = () => {
  const src = path.join(root, 'assets', 'dual-channel-icon.svg');
  const dest = path.join(root, 'public', 'dual-channel-icon.svg');
  fs.copyFileSync(src, dest);
};

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'sync-app-icon-from-assets',
      buildStart() {
        syncAppIconFromAssets();
      },
      configureServer() {
        syncAppIconFromAssets();
      },
    },
  ],
  server: {
    port: 5173,
  },
});
