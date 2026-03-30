import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteExternalsPlugin } from 'vite-plugin-externals';

const externalLibs: Record<string, string> = {
  react: 'React',
  'react-dom': 'ReactDOM',
  ReactDom: 'ReactDOM',
  '@mantine/core': 'MantineCore',
};

const externalKeys = Object.keys(externalLibs);

// Bump this version when deploying an updated enrich panel bundle.
const ENRICH_PANEL_ENTRY_NAME = 'enrich-panel-v14';

export default defineConfig({
  plugins: [
    react({
      jsxRuntime: 'classic',
    }),
    viteExternalsPlugin(externalLibs),
  ],
  build: {
    target: 'esnext',
    cssCodeSplit: false,
    manifest: true,
    sourcemap: true,
    rollupOptions: {
      preserveEntrySignatures: 'exports-only',
      input: {
        [ENRICH_PANEL_ENTRY_NAME]: './src/EnrichPanelV2.tsx',
        Settings: './src/Settings.tsx',
      },
      output: [
        {
          dir: '../inventree_import_plugin/static',
          entryFileNames: '[name].js',
          assetFileNames: 'assets/[name].[ext]',
          globals: externalLibs,
        },
        {
          dir: '../inventree_import_plugin/static',
          entryFileNames: '[name]-[hash].js',
          assetFileNames: 'assets/[name].[ext]',
          globals: externalLibs,
        },
      ],
      external: externalKeys,
    },
  },
  optimizeDeps: {
    exclude: externalKeys,
  },
});
