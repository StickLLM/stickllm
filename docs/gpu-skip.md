# GPU skip (0.6.3)

When `amdgpu` fails ring/gfx init (`ring … test failed`, `hw_init` error), StickLLM
records the PCI address under `/mnt/stickllm-data/gpu-skip/skip-pci.txt` and tries
to unbind that device so boot can continue on other GPUs / CPU.

On later boots, `stickllm-gpu-skip.service` re-applies the skip (unbind +
`driver_override=vfio-pci` best-effort).

Clear the skip: delete `/mnt/stickllm-data/gpu-skip/skip-pci.txt` and reboot.
This never formats disks and never touches NVIDIA binding beyond that PCI slot.
