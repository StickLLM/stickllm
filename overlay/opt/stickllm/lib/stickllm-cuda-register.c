/*
 * Preload shim: register ggml CUDA backend when libggml did not DT_NEEDED
 * libggml-cuda (e.g. after a CPU lib overwrite, or shared-backend builds that
 * export ggml_backend_cuda_reg instead of ggml_backend_init).
 *
 * Built by scripts/lib/docker-build-llama.sh into stickllm-cuda-register.so.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>

typedef void *ggml_backend_reg_t;
typedef ggml_backend_reg_t (*ggml_backend_cuda_reg_t)(void);
typedef void (*ggml_backend_register_t)(ggml_backend_reg_t);

__attribute__((constructor)) static void stickllm_cuda_register(void) {
  /*
   * Prefer the already-loaded libggml (RTLD_NOLOAD / RTLD_DEFAULT). A second
   * dlopen of libggml.so can create a private registry — CUDA inits there
   * while llama-server --list-devices still prints "(none)".
   */
  void *ggml = dlopen("libggml.so.1", RTLD_NOW | RTLD_GLOBAL | RTLD_NOLOAD);
  if (!ggml) {
    ggml = dlopen("libggml.so.0", RTLD_NOW | RTLD_GLOBAL | RTLD_NOLOAD);
  }
  if (!ggml) {
    ggml = dlopen("libggml.so", RTLD_NOW | RTLD_GLOBAL | RTLD_NOLOAD);
  }
  if (!ggml) {
    ggml = dlopen("libggml.so.1", RTLD_NOW | RTLD_GLOBAL);
  }
  if (!ggml) {
    ggml = dlopen("libggml.so.0", RTLD_NOW | RTLD_GLOBAL);
  }
  if (!ggml) {
    ggml = dlopen("libggml.so", RTLD_NOW | RTLD_GLOBAL);
  }

  void *cuda = dlopen("libggml-cuda.so", RTLD_NOW | RTLD_GLOBAL);
  if (!cuda) {
    cuda = dlopen("libggml-cuda.so.1", RTLD_NOW | RTLD_GLOBAL);
  }
  if (!cuda) {
    cuda = dlopen("libggml-cuda.so.0", RTLD_NOW | RTLD_GLOBAL);
  }
  if (!ggml || !cuda) {
    fprintf(stderr, "stickllm-cuda-register: dlopen failed: %s\n", dlerror());
    return;
  }

  ggml_backend_cuda_reg_t cuda_reg =
      (ggml_backend_cuda_reg_t)dlsym(cuda, "ggml_backend_cuda_reg");
  ggml_backend_register_t backend_register =
      (ggml_backend_register_t)dlsym(ggml, "ggml_backend_register");
  if (!backend_register) {
    backend_register =
        (ggml_backend_register_t)dlsym(RTLD_DEFAULT, "ggml_backend_register");
  }
  if (!cuda_reg || !backend_register) {
    fprintf(stderr,
            "stickllm-cuda-register: missing ggml_backend_cuda_reg or "
            "ggml_backend_register\n");
    return;
  }

  ggml_backend_reg_t reg = cuda_reg();
  if (!reg) {
    fprintf(stderr, "stickllm-cuda-register: ggml_backend_cuda_reg returned NULL\n");
    return;
  }
  backend_register(reg);
  fprintf(stderr, "stickllm-cuda-register: CUDA backend registered\n");

  /* CPU is required for host buffer types even on full GPU offload. */
  void *cpu = dlopen("libggml-cpu.so", RTLD_NOW | RTLD_GLOBAL);
  if (!cpu) {
    cpu = dlopen("libggml-cpu-x64.so", RTLD_NOW | RTLD_GLOBAL);
  }
  if (cpu) {
    typedef ggml_backend_reg_t (*ggml_backend_cpu_reg_t)(void);
    ggml_backend_cpu_reg_t cpu_reg =
        (ggml_backend_cpu_reg_t)dlsym(cpu, "ggml_backend_cpu_reg");
    if (cpu_reg) {
      ggml_backend_reg_t creg = cpu_reg();
      if (creg) {
        backend_register(creg);
        fprintf(stderr, "stickllm-cuda-register: CPU backend registered\n");
      }
    }
  }
}
