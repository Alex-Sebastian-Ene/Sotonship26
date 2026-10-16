"""``python -m sotonship26``: show which PyTorch build and accelerator this machine is using."""

import platform

import torch


def main() -> None:
    if torch.version.hip:
        build = f"ROCm {torch.version.hip}"
    elif torch.version.cuda:
        build = f"CUDA {torch.version.cuda}"
    else:
        build = "CPU"
    print(f"torch {torch.__version__} ({build}), Python {platform.python_version()}")
    if not torch.cuda.is_available():
        print("No GPU visible to torch.")
        return
    for i in range(torch.cuda.device_count()):
        major, minor = torch.cuda.get_device_capability(i)
        print(f"  cuda:{i} {torch.cuda.get_device_name(i)} (sm_{major}{minor})")
    x = torch.randn(1024, 1024, device="cuda")
    (x @ x).sum().item()
    print("GPU matmul OK")


if __name__ == "__main__":
    main()
