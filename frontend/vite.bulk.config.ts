import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    target: 'esnext',
    cssCodeSplit: false,
    emptyOutDir: false,
    sourcemap: true,
    rollupOptions: {
      preserveEntrySignatures: 'exports-only',
      input: ['./src/StandaloneBulkPage.tsx'],
      output: {
        dir: '../inventree_import_plugin/static/bulk',
        format: 'es',
        entryFileNames: 'StandaloneBulkPage-v3.js',
        assetFileNames: 'assets/[name].[ext]',
      },
    },
  },
});
