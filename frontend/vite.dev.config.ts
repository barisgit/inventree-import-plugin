import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import viteConfig from './vite.config';

export default defineConfig({
  ...viteConfig,
  plugins: [
    react({
      jsxRuntime: 'classic',
    }),
  ],
  server: {
    port: 5174,
    strictPort: true,
    cors: {
      preflightContinue: true,
      origin: '*',
    },
  },
});
