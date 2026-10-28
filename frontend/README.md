# Frontend

React + TypeScript + Vite web UI. It arrives in **M2** (session browser, shared timeline, camera, plot and top-down panels).

Design rules (see `CLAUDE.md`): the browser owns the playback clock and pulls data by time range; panels draw imperatively to canvas; decoding happens in Web Workers; everything is bundled for offline use (no runtime CDN).
