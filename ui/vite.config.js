// Component-mode plugin bundle only — Vite lib mode building
// src/plugin.jsx -> dist/mini-browser.js, the bundle aw-app.json's
// contributes.frontend.bundle points at. Same shape as
// aw-app-whiteboard's ui/vite.config.js.
import { defineConfig } from 'vite';

export default defineConfig({
  esbuild: {
    jsxFactory: 'host.h',
    jsxFragment: 'host.React.Fragment',
  },
  build: {
    outDir: 'dist',
    lib: {
      entry: 'src/plugin.jsx',
      formats: ['es'],
      fileName: () => 'mini-browser.js',
    },
    rollupOptions: {
      external: ['react', 'react-dom'],
    },
  },
});
