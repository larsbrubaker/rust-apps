# Rust Apps

[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/larsbrubaker)

A collection of Lars Brubaker's Rust libraries and applications. Each repository is included as a submodule so you can clone them all at once and keep them up to date.

## Clone with all submodules

```bash
git clone --recurse-submodules https://github.com/larsbrubaker/rust-apps.git
```

To update all submodules to their latest commits:

```bash
git submodule update --remote --merge
```

---

## Repositories

### [clipper2-rust](https://github.com/larsbrubaker/clipper2-rust)

Complete, pure Rust port of the [Clipper2 C++ library](https://github.com/AngusJohnson/Clipper2) by Angus Johnson — polygon clipping and offsetting with support for union, intersection, difference, and XOR operations.

[![clipper2-rust demo](https://raw.githubusercontent.com/larsbrubaker/clipper2-rust/main/docs/demo-screenshot.png)](https://larsbrubaker.github.io/clipper2-rust/)

[Live Demo](https://larsbrubaker.github.io/clipper2-rust/) · [Repository](https://github.com/larsbrubaker/clipper2-rust)

---

### [tess2-rust](https://github.com/larsbrubaker/tess2-rust)

Pure Rust port of [libtess2](https://github.com/memononen/libtess2) — the SGI tessellation library for converting complex polygons (including self-intersecting and with holes) into triangles.

[![tess2-rust demo](https://raw.githubusercontent.com/larsbrubaker/tess2-rust/main/demo/src/static/tess2.png)](https://larsbrubaker.github.io/tess2-rust/)

[Live Demo](https://larsbrubaker.github.io/tess2-rust/) · [Repository](https://github.com/larsbrubaker/tess2-rust)

---

### [agg-rust](https://github.com/larsbrubaker/agg-rust)

Pure Rust port of [Anti-Grain Geometry (AGG) 2.6](http://www.antigrain.com/) — a high-quality 2D vector graphics rendering engine with sub-pixel accuracy and anti-aliasing.

[![agg-rust demo](https://raw.githubusercontent.com/larsbrubaker/agg-rust/master/docs/screenshot.png)](https://larsbrubaker.github.io/agg-rust/)

[Live Demo](https://larsbrubaker.github.io/agg-rust/) · [Repository](https://github.com/larsbrubaker/agg-rust)

---

### [agg-gui](https://github.com/larsbrubaker/agg-gui)

A Rust GUI framework built on top of [agg-rust](https://github.com/larsbrubaker/agg-rust) — provides widgets, layout, and rendering for desktop applications using AGG as the rendering backend.  Immediate-mode widget tree, Y-up coordinates, halo-AA GL pipeline, multi-touch support.

[![agg-gui demo](https://raw.githubusercontent.com/larsbrubaker/agg-gui/main/agg-gui/readme_hero.png)](https://larsbrubaker.github.io/agg-gui/)

[![crates.io](https://img.shields.io/crates/v/agg-gui.svg)](https://crates.io/crates/agg-gui) · [Live Demo](https://larsbrubaker.github.io/agg-gui/) · [Repository](https://github.com/larsbrubaker/agg-gui)

---

### [manifold-rust](https://github.com/larsbrubaker/manifold-rust)

Pure Rust port of the [Manifold](https://github.com/elalish/manifold) 3D geometry library — fast, robust, watertight boolean operations on triangle meshes.

[![manifold-rust demo](https://raw.githubusercontent.com/larsbrubaker/manifold-rust/main/README_HERO.png)](https://larsbrubaker.github.io/manifold-rust/)

[Live Demo](https://larsbrubaker.github.io/manifold-rust/) · [Repository](https://github.com/larsbrubaker/manifold-rust)

---

### [Thingi10K](https://github.com/larsbrubaker/Thingi10K)

Searchable 3D model archive browser for the [Thingi10K dataset](https://ten-thousand-models.appspot.com/) — 10,000 Thingiverse models with mesh quality metadata. Built with Rust/WASM.

[![Thingi10K demo](https://raw.githubusercontent.com/larsbrubaker/Thingi10K/main/docs/screenshot.png)](https://larsbrubaker.github.io/Thingi10K/)

[Live Demo](https://larsbrubaker.github.io/Thingi10K/) · [Repository](https://github.com/larsbrubaker/Thingi10K)

---

### [atomartist](https://github.com/larsbrubaker/atomartist)

Visual node-based 3D design tool in pure Rust. Wire together typed nodes — primitives, transforms, boolean operations, extrusions, imported meshes — and watch the resulting 3D geometry update live in the viewport. Built on [agg-gui](https://github.com/larsbrubaker/agg-gui), [manifold-rust](https://github.com/larsbrubaker/manifold-rust), [clipper2-rust](https://github.com/larsbrubaker/clipper2-rust), and [tess2-rust](https://github.com/larsbrubaker/tess2-rust). Runs natively (Windows / macOS / Linux) and in the browser (WASM via WebGPU / WebGL2).

[![atomartist demo](https://raw.githubusercontent.com/larsbrubaker/atomartist/main/readme_hero.png)](https://larsbrubaker.github.io/atomartist/)

[Live Demo](https://larsbrubaker.github.io/atomartist/) · [Repository](https://github.com/larsbrubaker/atomartist)

---

### [antidote](https://github.com/larsbrubaker/antidote)

Bubble-trap virus puzzle game in Rust — rendered with [agg-gui](https://github.com/larsbrubaker/agg-gui), physics by [rapier2d](https://rapier.rs/), persisted to a multi-game Supabase Postgres backend. Runs natively (winit + wgpu) and in the browser (WebAssembly).

[![antidote demo](https://raw.githubusercontent.com/larsbrubaker/antidote/main/readme_hero.png)](https://larsbrubaker.github.io/antidote/)

[Live Demo](https://larsbrubaker.github.io/antidote/) · [Repository](https://github.com/larsbrubaker/antidote)

---

### [solitaire](https://github.com/larsbrubaker/solitaire)

Four solitaire variants in Rust — Klondike, FreeCell, Spider, and Microsoft-style Classic. Rendered with [agg-gui](https://github.com/larsbrubaker/agg-gui), persisted to the same Supabase backend as antidote. Runs natively (winit + wgpu) and in the browser (WebAssembly).

[![solitaire demo](https://raw.githubusercontent.com/larsbrubaker/solitaire/main/readme_hero.png)](https://larsbrubaker.github.io/solitaire/)

[Live Demo](https://larsbrubaker.github.io/solitaire/) · [Repository](https://github.com/larsbrubaker/solitaire)

---

### [instant-astronomer](https://github.com/larsbrubaker/instant-astronomer)

Point your phone at the sky and see what you're looking at — stars, planets, the Sun, the Moon, constellations, all driven by your location, the current time, and (on mobile) the device's compass + IMU. Tap any bright object to identify it: "that's Venus, magnitude −4.4." Rendered entirely through [agg-gui](https://github.com/larsbrubaker/agg-gui) — no separate WebGL / wgpu 3-D pipeline. Runs natively (winit + wgpu) and in the browser (WebAssembly).

[![instant-astronomer demo](https://raw.githubusercontent.com/larsbrubaker/instant-astronomer/master/readme_hero.png)](https://larsbrubaker.github.io/instant-astronomer/)

[Live Demo](https://larsbrubaker.github.io/instant-astronomer/) · [Repository](https://github.com/larsbrubaker/instant-astronomer)
