"""Supported dense embedding profiles for both ingestion and retrieval."""

DEFAULT_MODEL = "e5-small"
MODELS = {
    "e5-small": {
        "name": "E5 multilingual small",
        "model": "intfloat/multilingual-e5-small",
        "collection": "documents",
        "dimensions": 384,
        "batch_size": 32,
        "resources": "Low",
        "speed": "Fastest CPU option",
        "use_case": "Recommended for small VMs and mixed-language document libraries.",
        "note": "Best starting point when indexing speed and memory matter.",
        "url": "https://huggingface.co/intfloat/multilingual-e5-small",
    },
    "e5-base": {
        "name": "E5 multilingual base",
        "model": "intfloat/multilingual-e5-base",
        "collection": "documents_e5_base",
        "dimensions": 768,
        "batch_size": 16,
        "resources": "Medium",
        "speed": "Slower than E5 small on CPU",
        "use_case": "Mixed-language search when the VM has more CPU and RAM.",
        "note": "Larger vectors use more Qdrant storage. Evaluate retrieval on your own documents.",
        "url": "https://huggingface.co/intfloat/multilingual-e5-base",
    },
    "bge-m3": {
        "name": "BGE-M3",
        "model": "BAAI/bge-m3",
        "collection": "documents_bge_m3",
        "dimensions": 1024,
        "batch_size": 4,
        "resources": "High",
        "speed": "Slowest CPU option",
        "use_case": "Multilingual search on a VM with ample memory and CPU time.",
        "note": "This app uses its dense vectors only; documents are still split into short chunks.",
        "url": "https://huggingface.co/BAAI/bge-m3",
    },
}


def document_text(model_name, text):
    return text if model_name == "BAAI/bge-m3" else f"passage: {text}"


def query_text(model_name, text):
    return text if model_name == "BAAI/bge-m3" else f"query: {text}"
