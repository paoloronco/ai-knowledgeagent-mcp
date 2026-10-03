import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[1] / "knowledge-mcp"
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
    def test_sensitive_directories_remain_excluded_with_an_older_policy(self):
        names = ("coverage", "cache", ".cache", "vendor", ".stversions", "sample-folder", "sample-folder", "sample-folder", "sample-folder")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "documents"
            root.mkdir()
            old_policy = (ROOT / "mcp" / "index-policy.yaml").read_text(encoding="utf-8")
            for name in names:
                old_policy = old_policy.replace(f"  - {name}\n", "")
            policy_file = Path(tmp) / "old-policy.yaml"
            policy_file.write_text(old_policy, encoding="utf-8")
            with patch.object(ingest, "POLICY_FILE", policy_file), patch.dict(os.environ, {"KNOWLEDGE_ROOT": str(root)}):
                policy = ingest.load_policy()
            self.assertTrue({name.casefold() for name in names} <= {name.casefold() for name in policy["exclude_directories"]})
            for name in names:
                folder = root / "notes" / name.upper()
                folder.mkdir(parents=True, exist_ok=True)
                document = folder / "private.md"
                document.write_text("Sensitive", encoding="utf-8")
                self.assertFalse(ingest.is_candidate(document, root, policy), name)
                self.assertFalse(retrieval.eligible_for_query(document.relative_to(root).as_posix(), "current"), name)

    def test_selected_folders_and_file_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("team-a", "team-b", "sample-folder"):
                (root / name).mkdir()
                (root / name / "note.md").write_text("Visible content", encoding="utf-8")
            (root / "team-a" / "skip.md").write_text("Excluded content", encoding="utf-8")
            with patch.dict(os.environ, {"KNOWLEDGE_ROOT": str(root)}):
                policy = ingest.load_policy()
            policy["exclude_files"] = ["skip.md"]
            with patch.dict(os.environ, {"INDEX_SOURCE_PATHS": json.dumps(["team-a", "team-b", "sample-folder"])}):
                paths = ingest.discover_documents(policy)
            self.assertEqual({p.relative_to(root).as_posix() for p in paths}, {"team-a/note.md", "team-b/note.md"})

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
                unchanged_state = state_file.read_bytes()
                ingest.main()
                self.assertEqual(state_file.read_bytes(), unchanged_state)

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
                with self.assertRaises(SystemExit):
                    ingest.main()
                self.assertGreater(client.count(ingest.COLLECTION_NAME).count, 0)
                with patch.object(sys, "argv", ["ingest.py", "--allow-empty"]):
                    ingest.main()
                self.assertEqual(client.count(ingest.COLLECTION_NAME).count, 0)


if __name__ == "__main__":
    unittest.main()
