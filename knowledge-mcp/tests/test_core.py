import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingestion"))
sys.path.insert(0, str(ROOT / "mcp"))
import ingest
import retrieval


class FakeVector:
    def tolist(self):
        return [1.0, 0.0, 0.0]


class FakeModel:
    def __init__(self, *args, **kwargs):
        pass

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, inputs, **kwargs):
        return [FakeVector() for _ in inputs]


class CoreFlowTest(unittest.TestCase):
    def test_expansion_stays_in_section(self):
        def point(section, chunk, text):
            return types.SimpleNamespace(payload={
                "document_id": "same-file", "section_index": section,
                "chunk_index": chunk, "file_size": 20000, "text": text,
            })

        selected = point(0, 0, "relevant")
        with patch.object(retrieval, "CORPUS", [selected, point(1, 0, "unrelated")]):
            expanded = retrieval.expand_result_context({"payload": selected.payload})
        self.assertIn("relevant", expanded["text"])
        self.assertNotIn("unrelated", expanded["text"])

    def test_ingest_update_delete_and_retrieval_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "docs"
            root.mkdir()
            source = root / "note.md"
            source.write_text("Qdrant configuration. " * 10 + "\npassword: supersecret\n", encoding="utf-8")
            excluded = root / "sample-folder"
            excluded.mkdir()
            (excluded / "private.md").write_text("Must stay out of Qdrant. " * 10, encoding="utf-8")
            state_file = Path(tmp) / "state.json"
            client = QdrantClient(":memory:")
            fake_transformers = types.SimpleNamespace(SentenceTransformer=FakeModel)
            with (
                patch.dict(os.environ, {"KNOWLEDGE_ROOT": str(root)}),
                patch.dict(sys.modules, {"sentence_transformers": fake_transformers}),
                patch.object(ingest, "QdrantClient", return_value=client),
                patch.object(ingest, "STATE_FILE", state_file),
                patch.object(ingest, "ERROR_LOG", Path(tmp) / "errors.log"),
                patch.object(sys, "argv", ["ingest.py"]),
            ):
                with patch.object(sys, "argv", ["ingest.py", "--dry-run", "--limit", "1"]):
                    ingest.main()
                self.assertFalse(client.get_collections().collections)
                ingest.main()
                self.assertGreater(client.count(ingest.COLLECTION_NAME).count, 0)
                self.assertEqual(len(json.loads(state_file.read_text(encoding="utf-8"))["documents"]), 1)

                retrieval.client = client
                retrieval.CORPUS = None
                retrieval.model = FakeModel()
                result = retrieval.search("Qdrant configuration")
                self.assertTrue(result["results"])
                self.assertIn("[REDACTED]", result["results"][0]["text"])
                self.assertFalse(retrieval.eligible_for_query(r"Projects\sample-folder\secret.md", "current"))

                source.write_text("New Qdrant configuration. " * 10, encoding="utf-8")
                ingest.main()
                self.assertEqual(len(json.loads(state_file.read_text(encoding="utf-8"))["documents"]), 1)
                source.unlink()
                ingest.main()
                self.assertEqual(client.count(ingest.COLLECTION_NAME).count, 0)


if __name__ == "__main__":
    unittest.main()
