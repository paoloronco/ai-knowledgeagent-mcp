"""Choose the device used by document and query embeddings."""

import os


def embedding_device():
    preference = os.getenv("EMBEDDING_DEVICE", "auto").lower()
    if preference not in {"auto", "cpu", "cuda"}:
        raise ValueError("EMBEDDING_DEVICE must be auto, cpu, or cuda")
    if preference == "cpu":
        return "cpu"

    import torch

    available = torch.cuda.is_available()
    if preference == "cuda" and not available:
        raise RuntimeError("CUDA was requested but PyTorch cannot use an NVIDIA GPU")
    return "cuda" if available else "cpu"
