# AWTK KX6625 Port

This directory contains project-owned AWTK integration files for the KX6625/QEMU
platform. It is intentionally separate from `third_party/awtk`, which is the
upstream AWTK source tree.

- `port/awtk_config.h` provides the minimal embedded AWTK configuration used by
  the firmware build.
- `port/platform_qemu.c` provides time, sleep, heap, assert, and libc shim code
  needed by AWTK on the FreeRTOS firmware.
- `port/main_loop_qemu_raw.c` provides the raw AWTK LCD/main-loop platform hook
  for the RGB565 framebuffer path.

Build the demo with:

```sh
make -C firmware AWTK_DEMO=1
```

Run the visual validation with:

```sh
DISPLAY_KEEPALIVE=0 AWTK_DEMO=1 ICOUNT_SHIFT=5 bash scripts/display_interactive.sh
```