import math
import os
import re
from pathlib import PurePosixPath

from qdrant_client import QdrantClient
from policy_defaults import REQUIRED_DIRECTORY_NAMES
from embedding_models import query_text


QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
DENSE_COLLECTION = os.getenv("DENSE_COLLECTION", "documents")
MODEL_NAME = os.getenv("MODEL_NAME", "intfloat/multilingual-e5-small")

DENSE_LIMIT = 60
LEXICAL_LIMIT = 60
FINAL_LIMIT = 8


STOPWORDS = {
    "come", "cosa", "quale", "quali", "dove", "quando",
    "perché", "perche", "nel", "nella", "nelle", "nei",
    "del", "della", "delle", "dei", "degli",
    "mio", "mia", "miei", "mie",
    "è", "e", "sono", "un", "una",
    "il", "lo", "la", "gli", "le",
    "di", "da", "a", "in", "su",
    "configurato", "configurazione",

    "the", "what", "how", "where", "when",
    "is", "are", "my", "of", "to", "and", "for",
}


GENERIC_TERMS = {
    "homelab",
    "server",
    "rete",
    "network",
    "sistema",
    "system",
    "servizio",
    "service",
    "sicurezza",
    "security",
    "infrastruttura",
    "infrastructure",
    "progetto",
    "project",

    # Temporal / conversational terms must influence intent,
    # never technical entity anchoring.
    "prima",
    "vecchio",
    "vecchia",
    "precedente",
    "precedentemente",
    "storico",
    "storica",
    "dismesso",
    "dismessa",
    "passato",
    "avevo",
    "old",
    "previous",
    "historical",
    "formerly",
}

KNOWN_TECH_ENTITIES = {
    "proxmox",
    "cloudflare",
    "n8n",
    "orbitpage",
    "splunk",
    "qdrant",
    "wazuh",
    "docker",
    "portainer",
    "ansible",
    "unifi",
    "nginx",
    "wordpress",
    "tailscale",
    "grafana",
    "home assistant",
    "elastic",
    "elasticsearch",
    "kubernetes",
    "terraform",
    "oracle cloud",
    "hetzner",
    "syncthing",
    "photoprism",
}



HISTORICAL_MARKERS = (
    "/dismessi/",
    "/old/",
    "/backup/",
    "/backups/",
    "/archive/",
    "/archivio/",
)


# Material that should not normally participate in the personal
# technical knowledge agent.
RESTRICTED_MARKERS = tuple(f"/{name}/" for name in sorted(REQUIRED_DIRECTORY_NAMES))


CURRENT_QUERY_HINTS = (
    "attuale",
    "attualmente",
    "adesso",
    "ora",
    "current",
    "currently",
    "oggi",
    "configurato",
    "configurata",
    "configurazione",
    "come è",
    "come e",
)


HISTORICAL_QUERY_HINTS = (
    "prima",
    "vecchio",
    "vecchia",
    "precedente",
    "precedentemente",
    "storico",
    "storica",
    "dismesso",
    "dismessa",
    "in passato",
    "avevo",
    "era configurato",
    "old",
    "previous",
    "historical",
    "formerly",
)


client = QdrantClient(url=QDRANT_URL)

model = None


def load_corpus():
    points = []
    offset = None

    while True:
        batch, offset = client.scroll(
            collection_name=DENSE_COLLECTION,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        points.extend(batch)

        if offset is None:
            break

    return points


CORPUS = None


def normalized_path(source):
    return "/" + (source or "").lower().replace("\\", "/").strip("/") + "/"


def tokenize(text):
    return [
        token.lower()
        for token in re.findall(
            r"[a-zA-ZÀ-ÿ0-9_.+-]+",
            text,
        )
        if len(token) >= 3
        and token.lower() not in STOPWORDS
    ]


def classify_source(source):
    s = normalized_path(source)

    if any(
        marker in s
        for marker in RESTRICTED_MARKERS
    ):
        eligibility = "restricted"
    else:
        eligibility = "normal"

    if any(
        marker in s
        for marker in HISTORICAL_MARKERS
    ):
        lifecycle = "historical"
    else:
        lifecycle = "current_or_unknown"

    # Specific semantic categories must take precedence
    # over generic /docs/ paths.

    if (
        "/certificati/" in s
        or "/certifications/" in s
        or "/certificate/" in s
        or "/certification/" in s
    ):
        source_type = "certification"
        authority = "low"

    elif (
        "/configurazioni/" in s
        or "/configuration/" in s
        or "/config/" in s
        or "configuration" in s
    ):
        source_type = "configuration"
        authority = "high"

    elif (
        "/marketing/" in s
        or "/promo/" in s
        or "transcript." in s
    ):
        source_type = "marketing"
        authority = "low"

    elif (
        "/.vercel/output/" in s
        or "/dist/" in s
        or "/build/" in s
    ):
        source_type = "generated"
        authority = "low"

    elif (
        "/docs/" in s
        or "/documentation/" in s
        or "/guides/" in s
    ):
        source_type = "technical_documentation"
        authority = "high"

    elif s.startswith("/projects/"):
        source_type = "project"
        authority = "medium_high"

    elif s.startswith("/sito/"):
        source_type = "website"
        authority = "medium"

    elif s.startswith("/documenti/"):
        source_type = "document"
        authority = "medium"

    else:
        source_type = "other"
        authority = "medium"

    return {
        "eligibility": eligibility,
        "lifecycle": lifecycle,
        "authority": authority,
        "source_type": source_type,
    }

def detect_temporal_intent(query):
    q = query.lower()

    if any(
        hint in q
        for hint in HISTORICAL_QUERY_HINTS
    ):
        return "historical"

    if any(
        hint in q
        for hint in CURRENT_QUERY_HINTS
    ):
        return "current"

    # Personal infrastructure questions default to current.
    return "current"


def detect_query_intent(query):
    q = query.lower()

    configuration_hints = (
        "configurato",
        "configurata",
        "configurazione",
        "configuration",
        "configured",
        "config",
        "setup",
        "installato",
        "installata",
        "installazione",
        "architettura",
        "architecture",
        "deployment",
        "deploy",
        "porta",
        "porte",
        "indirizzo ip",
    )

    project_hints = (
        "progetti",
        "progetto",
        "projects",
        "project",
        "cosa ho fatto",
        "integrazioni",
    )

    if any(
        hint in q
        for hint in configuration_hints
    ):
        return "configuration"

    if any(
        hint in q
        for hint in project_hints
    ):
        return "projects"

    return "general"


def eligible_for_query(source, temporal_intent):
    meta = classify_source(source)

    if meta["eligibility"] == "restricted":
        return False

    if (
        temporal_intent == "current"
        and meta["lifecycle"] == "historical"
    ):
        return False

    return True


def extract_anchors(query):
    q = query.lower()

    # Known technical entities are always anchors,
    # regardless of how common they are in the corpus.
    known = []

    for entity in sorted(
        KNOWN_TECH_ENTITIES,
        key=len,
        reverse=True,
    ):
        if entity not in q:
            continue

        matches = 0

        for point in CORPUS:
            payload = point.payload or {}
            source = payload.get("source") or ""

            if (
                classify_source(source)["eligibility"]
                == "restricted"
            ):
                continue

            searchable = "\n".join(
                [
                    source.lower(),
                    (payload.get("filename") or "").lower(),
                    (payload.get("text") or "").lower(),
                ]
            )

            if entity in searchable:
                matches += 1

        known.append(
            {
                "term": entity,
                "matches": matches,
                "kind": "known_entity",
            }
        )

    if known:
        return known[:2]

    # Otherwise fall back to rare discriminating terms.
    terms = list(dict.fromkeys(tokenize(query)))

    candidates = [
        term
        for term in terms
        if term not in GENERIC_TERMS
    ]

    anchors = []

    for term in candidates:
        matches = 0

        for point in CORPUS:
            payload = point.payload or {}
            source = payload.get("source") or ""

            if (
                classify_source(source)["eligibility"]
                == "restricted"
            ):
                continue

            searchable = "\n".join(
                [
                    source.lower(),
                    (payload.get("filename") or "").lower(),
                    (payload.get("text") or "").lower(),
                ]
            )

            if term in searchable:
                matches += 1

        if 0 < matches <= 500:
            anchors.append(
                {
                    "term": term,
                    "matches": matches,
                    "kind": "rare_term",
                }
            )

    anchors.sort(
        key=lambda x: x["matches"]
    )

    return anchors[:2]


def candidate_corpus(
    anchors,
    temporal_intent,
):
    anchor_terms = [
        item["term"]
        for item in anchors
    ]

    selected = []

    for point in CORPUS:
        payload = point.payload or {}

        source = payload.get("source") or ""

        if not eligible_for_query(
            source,
            temporal_intent,
        ):
            continue

        if not anchor_terms:
            selected.append(point)
            continue

        searchable = "\n".join(
            [
                source.lower(),
                (payload.get("filename") or "").lower(),
                (payload.get("text") or "").lower(),
            ]
        )

        if any(
            term in searchable
            for term in anchor_terms
        ):
            selected.append(point)

    return selected


def lexical_search(
    query,
    candidates,
):
    terms = tokenize(query)

    results = []

    for point in candidates:
        payload = point.payload or {}

        text = (payload.get("text") or "").lower()
        source = (payload.get("source") or "").lower()
        filename = (payload.get("filename") or "").lower()

        score = 0.0
        matched_terms = 0

        for term in terms:
            term_score = 0.0

            occurrences = text.count(term)

            if occurrences:
                term_score += (
                    1.0
                    + math.log1p(occurrences)
                )

            if term in filename:
                term_score += 4.0

            if term in source:
                term_score += 3.0

            if term_score > 0:
                matched_terms += 1
                score += term_score

        if terms and matched_terms:
            coverage = (
                matched_terms / len(terms)
            )

            score *= (
                1.0 + coverage
            )

        if score > 0:
            results.append(
                {
                    "id": point.id,
                    "score": score,
                    "payload": payload,
                }
            )

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return results[:LEXICAL_LIMIT]


def dense_search(query):
    vector = model.encode(
        [query_text(MODEL_NAME, query)],
        normalize_embeddings=True,
    )[0]

    return client.query_points(
        collection_name=DENSE_COLLECTION,
        query=vector.tolist(),
        limit=DENSE_LIMIT,
        with_payload=True,
    ).points


def reciprocal_rank_fusion(
    dense_results,
    lexical_results,
    anchors,
    temporal_intent,
    k=60,
):
    fused = {}

    # Dense results must pass policy too.
    for rank, result in enumerate(
        dense_results,
        start=1,
    ):
        payload = result.payload or {}
        source = payload.get("source") or ""

        if not eligible_for_query(
            source,
            temporal_intent,
        ):
            continue

        fused[result.id] = {
            "score": 1 / (k + rank),
            "payload": payload,
            "dense_rank": rank,
            "lexical_rank": None,
        }

    lexical_weight = (
        2.0 if anchors else 1.0
    )

    for rank, result in enumerate(
        lexical_results,
        start=1,
    ):
        entry = fused.setdefault(
            result["id"],
            {
                "score": 0.0,
                "payload": result["payload"],
                "dense_rank": None,
                "lexical_rank": None,
            },
        )

        entry["score"] += (
            lexical_weight
            / (k + rank)
        )

        entry["lexical_rank"] = rank

    return list(fused.values())


def apply_metadata_ranking(
    results,
    anchors,
    query_intent="general",
    temporal_intent="current",
):
    anchor_terms = [
        item["term"]
        for item in anchors
    ]

    authority_multiplier = {
        "high": 1.35,
        "medium_high": 1.15,
        "medium": 1.00,
        "low": 0.60,
    }

    general_types = {
        "configuration": 1.25,
        "technical_documentation": 1.20,
        "project": 1.05,
        "document": 1.00,
        "website": 0.85,
        "generated": 0.65,
        "marketing": 0.50,
        "certification": 0.40,
        "other": 0.90,
    }

    configuration_types = {
        "configuration": 1.70,
        "technical_documentation": 1.45,
        "project": 0.95,
        "document": 0.90,
        "website": 0.65,
        "generated": 0.45,
        "marketing": 0.35,
        "certification": 0.25,
        "other": 0.75,
    }

    project_types = {
        "project": 1.45,
        "technical_documentation": 1.10,
        "configuration": 1.05,
        "website": 1.00,
        "document": 0.90,
        "generated": 0.65,
        "marketing": 0.65,
        "certification": 0.35,
        "other": 0.85,
    }

    if query_intent == "configuration":
        type_multiplier = configuration_types
    elif query_intent == "projects":
        type_multiplier = project_types
    else:
        type_multiplier = general_types

    for item in results:
        payload = item["payload"]

        source = payload.get("source") or ""
        meta = classify_source(source)

        searchable = "\n".join(
            [
                source.lower(),
                (payload.get("filename") or "").lower(),
                (payload.get("text") or "").lower(),
            ]
        )

        # Strong preference for documents actually containing
        # the detected technical entity.
        if anchor_terms and any(
            term in searchable
            for term in anchor_terms
        ):
            item["score"] *= 1.50

        item["score"] *= entity_affinity(
            source,
            anchors,
        )

        item["score"] *= authority_multiplier.get(
            meta["authority"],
            1.0,
        )

        item["score"] *= type_multiplier.get(
            meta["source_type"],
            1.0,
        )

        # For explicitly historical questions, historical material
        # is not merely allowed: it is useful evidence.
        if (
            temporal_intent == "historical"
            and meta["lifecycle"] == "historical"
        ):
            item["score"] *= 1.25

        item["metadata"] = meta

    return results


def entity_affinity(source, anchors):
    """
    Estimate whether a source is structurally about the requested
    technical entity, rather than merely mentioning it in its text.

    Returns:
      1.35 = strong structural affinity
      1.15 = filename affinity
      1.00 = no additional affinity
    """

    if not anchors:
        return 1.0

    source_l = (source or "").lower()

    path_parts = [
        part.lower()
        for part in PurePosixPath(source_l).parts
    ]

    filename = (
        PurePosixPath(source_l).name
        if source_l
        else ""
    )

    for anchor in anchors:
        term = anchor["term"].lower()

        # Strongest signal:
        # entity appears as or inside a directory component.
        for part in path_parts[:-1]:
            if term in part:
                return 1.35

        # Weaker but useful signal:
        # entity appears in the actual filename.
        if term in filename:
            return 1.15

    return 1.0


def source_family(source):
    """
    Build a coarse canonical family for near-duplicate sources.

    This collapses common differences such as:
    - IT vs EN content copies
    - index.html wrappers
    - mirrored repository paths
    - generated website copies

    It does not alter or delete any indexed document.
    """

    source_l = (source or "").lower().replace("\\", "/")

    name = PurePosixPath(source_l).name

    # index.html carries little identity: use parent directory.
    if name in {
        "index.html",
        "index.htm",
        "home.html",
    }:
        name = PurePosixPath(source_l).parent.name

    # Remove common document extension.
    name = re.sub(
        r"\.(md|txt|html?|pdf|docx|pptx)$",
        "",
        name,
    )

    # Remove language markers.
    name = re.sub(
        r"(^|[-_.])(it|en)([-_.]|$)",
        "-",
        name,
    )

    # Remove common generated/copy suffixes.
    name = re.sub(
        r"(^|[-_.])(copy|backup|mirror)([-_.]|$)",
        "-",
        name,
    )

    # Normalize punctuation.
    name = re.sub(
        r"[^a-z0-9]+",
        "-",
        name,
    ).strip("-")

    # If normalization became useless, fall back to full source.
    if len(name) < 6:
        return source_l

    return name


def diversify(results):
    selected = []

    seen_sources = set()
    seen_families = set()

    for item in results:
        source = (
            item["payload"].get("source")
            or ""
        )

        source_key = source.lower()
        family = source_family(source)

        if source_key in seen_sources:
            continue

        if family in seen_families:
            continue

        selected.append(item)

        seen_sources.add(source_key)
        seen_families.add(family)

        if len(selected) >= FINAL_LIMIT:
            break

    return selected


def expand_result_context(item):
    """
    Retrieval v2.2 document expansion.

    For small documents, return the complete document context.

    For larger documents, return the matched chunk together with
    nearby chunks from the same document.

    Expansion happens before Secret Guard sanitization.
    """

    payload = item.get("payload") or {}

    document_id = payload.get("document_id")
    chunk_index = payload.get("chunk_index")
    file_size = payload.get("file_size") or 0

    if not document_id or chunk_index is None:
        return {
            "text": payload.get("text") or "",
            "expanded": False,
            "expansion_mode": "none",
            "expanded_chunks": 1,
        }

    document_points = [
        point
        for point in CORPUS
        if (
            (point.payload or {}).get("document_id")
            == document_id
        )
    ]

    if not document_points:
        return {
            "text": payload.get("text") or "",
            "expanded": False,
            "expansion_mode": "none",
            "expanded_chunks": 1,
        }

    document_points.sort(key=lambda point: (
        (point.payload or {}).get("section_index", 0),
        (point.payload or {}).get("chunk_index", 0),
    ))

    # Small technical documents are cheap enough to provide
    # completely and often contain configuration spread across
    # several adjacent chunks.
    if file_size <= 12000:
        selected = document_points
        mode = "full_document"

    else:
        lower = max(
            0,
            int(chunk_index) - 2,
        )

        upper = int(chunk_index) + 2

        selected = [
            point
            for point in document_points
            if (
                (point.payload or {}).get("section_index") == payload.get("section_index")
                and
                lower
                <= int(
                    (point.payload or {}).get(
                        "chunk_index",
                        -999999,
                    )
                )
                <= upper
            )
        ]

        mode = "neighbors"

    texts = []

    for point in selected:
        point_payload = point.payload or {}
        text = point_payload.get("text") or ""

        if text:
            texts.append(text)

    if not texts:
        return {
            "text": payload.get("text") or "",
            "expanded": False,
            "expansion_mode": "none",
            "expanded_chunks": 1,
        }

    return {
        "text": "\n\n".join(texts),
        "expanded": True,
        "expansion_mode": mode,
        "expanded_chunks": len(texts),
    }


def redact_secrets(text):
    """Secret Guard v2.1: redact credentials before retrieval output leaves the MCP boundary."""

    if not text:
        return text

    value = str(text)

    # Private keys.
    value = re.sub(
        r"(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        value,
    )

    # Authorization headers.
    value = re.sub(
        r"(?im)^(\s*(?:authorization|proxy-authorization)\s*:\s*)[^\r\n]+",
        r"\1[REDACTED]",
        value,
    )

    # Assignment-style credentials.
    # Examples: QDRANT_API_KEY=x, password: x, export TOKEN=x.
    assignment_pattern = (
        r"(?im)^(\s*(?:export\s+)?[`\"\']?"
        r"[A-Za-z0-9_.-]*(?:password|passwd|pwd|psw|api[_ -]?key|apikey|"
        r"client[_ -]?secret|access[_ -]?token|refresh[_ -]?token|"
        r"auth[_ -]?token|bearer[_ -]?token|private[_ -]?key|secret|token)"
        r"[A-Za-z0-9_.-]*[`\"\']?\s*[:=]\s*)[^\r\n]+"
    )
    value = re.sub(
        assignment_pattern,
        r"\1[REDACTED]",
        value,
    )

    # Label-style credentials.
    value = re.sub(
        r"(?im)^(\s*(?:password|passwd|pwd|psw|api[ _-]?key|client[ _-]?secret|access[ _-]?token|refresh[ _-]?token)\s+)\S[^\r\n]*",
        r"\1[REDACTED]",
        value,
    )

    # Bearer credentials anywhere in a line/prose.
    # Handles Bearer TOKEN, Bearer: TOKEN, Bearer=`TOKEN`, etc.
    value = re.sub(
        r"(?i)\bBearer\b[\s:`\'\"=-]+[A-Za-z0-9._~+/=-]{8,}",
        "Bearer [REDACTED]",
        value,
    )

    # Well-known credential formats.
    value = re.sub(
        r"\bsk-[A-Za-z0-9_-]{16,}\b",
        "[REDACTED API KEY]",
        value,
    )
    value = re.sub(
        r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
        "[REDACTED TOKEN]",
        value,
    )
    value = re.sub(
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
        "[REDACTED TOKEN]",
        value,
    )
    value = re.sub(
        r"\bAIza[0-9A-Za-z_-]{30,}\b",
        "[REDACTED API KEY]",
        value,
    )
    value = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "[REDACTED TOKEN]",
        value,
    )

    # Credentials embedded in URLs.
    value = re.sub(
        r"(?i)\b(https?|mongodb(?:\+srv)?|postgres(?:ql)?|mysql)://([^/\s:@]+):([^@\s/]+)@",
        r"\1://\2:[REDACTED]@",
        value,
    )

    return value

def sanitize_results(result):
    """
    Sanitize all retrieved text before returning the result
    to MCP or any other caller.
    """

    for item in result.get("results", []):
        for key, value in item.items():
            if isinstance(value, str):
                item[key] = redact_secrets(value)

    result["secret_guard"] = {
        "enabled": True,
        "mode": "retrieval-output-redaction",
    }

    return result


def search(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError("query must be a non-empty string of at most 1000 characters")

    global CORPUS, model
    if CORPUS is None:
        CORPUS = load_corpus()
    if model is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(MODEL_NAME, device="cpu")

    temporal_intent = (
        detect_temporal_intent(query)
    )

    query_intent = (
        detect_query_intent(query)
    )

    anchors = extract_anchors(query)

    candidates = candidate_corpus(
        anchors,
        temporal_intent,
    )

    lexical = lexical_search(
        query,
        candidates,
    )

    dense = dense_search(query)

    fused = reciprocal_rank_fusion(
        dense,
        lexical,
        anchors,
        temporal_intent,
    )

    fused = apply_metadata_ranking(
        fused,
        anchors,
        query_intent=query_intent,
        temporal_intent=temporal_intent,
    )

    fused.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    results = diversify(fused)

    # Retrieval v2.2:
    # enrich the strongest results with surrounding document
    # context so the agent normally needs only one MCP search.
    expansions = {}

    expanded_documents = 0
    max_expanded_documents = 2

    expandable_types = {
        "configuration",
        "technical_documentation",
        "project",
    }

    for item in results:
        source = (
            item["payload"].get("source")
            or ""
        )

        affinity = entity_affinity(
            source,
            anchors,
        )

        source_type = (
            item["metadata"]["source_type"]
        )

        should_expand = (
            query_intent == "configuration"
            and affinity >= 1.35
            and source_type in expandable_types
            and expanded_documents
            < max_expanded_documents
        )

        if should_expand:
            expansion = expand_result_context(
                item
            )

            if expansion["expanded"]:
                expanded_documents += 1

        else:
            expansion = {
                "text": (
                    item["payload"].get("text")
                    or ""
                ),
                "expanded": False,
                "expansion_mode": "none",
                "expanded_chunks": 1,
            }

        expansions[id(item)] = expansion

    result = {
        "query": query,

        "temporal_intent": temporal_intent,

        "query_intent": query_intent,

        "anchors": anchors,

        "candidate_chunks": len(candidates),

        "result_count": len(results),

        "retrieval_policy": {
            "historical_sources_allowed": (
                temporal_intent
                == "historical"
            ),
            "restricted_sources_excluded": True,
            "prefer_current_sources": True,
            "prefer_technical_documentation": True,
        },

        "results": [
            {
                "score": round(
                    item["score"],
                    6,
                ),

                "dense_rank": item[
                    "dense_rank"
                ],

                "lexical_rank": item[
                    "lexical_rank"
                ],

                "source": item[
                    "payload"
                ].get("source"),

                "page": item[
                    "payload"
                ].get("page"),

                "section": item[
                    "payload"
                ].get("section"),

                "lifecycle": item[
                    "metadata"
                ]["lifecycle"],

                "authority": item[
                    "metadata"
                ]["authority"],

                "source_type": item[
                    "metadata"
                ]["source_type"],

                "expanded": expansions[
                    id(item)
                ]["expanded"],

                "expansion_mode": expansions[
                    id(item)
                ]["expansion_mode"],

                "expanded_chunks": expansions[
                    id(item)
                ]["expanded_chunks"],

                "text": expansions[
                    id(item)
                ]["text"],

            }
            for item in results
        ],
    }

    return sanitize_results(result)
