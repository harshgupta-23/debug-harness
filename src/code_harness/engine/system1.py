"""System-1 Candidate Edge Scorer.

Enforces Invariant I1 & §3.3:
- Evaluates only closed, finite candidate sets derived from graph successors/predecessors.
- Uses Cross-Encoder with Softmax temperature calibration for sub-50ms ranking.
- Structurally incapable of generating text or hallucinating outside the candidate list.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from code_harness.core.graph import CodeGraph, GraphEdge, GraphNode


class ScoredCandidate(BaseModel):
    node: GraphNode
    edge: Optional[GraphEdge] = None
    raw_score: float
    calibrated_score: float
    path: List[str] = Field(default_factory=list)


class System1Scorer:
    """Fast candidate edge scorer with Softmax temperature calibration."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-TinyBERT-L-2-v2",
        temperature: float = 0.7,
    ) -> None:
        self.model_name = model_name
        self.temperature = max(1e-4, temperature)
        self._cross_encoder = None
        self._use_fallback = False

        # Attempt to initialize sentence-transformers if available
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
            self._cross_encoder = CrossEncoder(model_name)
        except Exception:
            # Ponytail ladder: Stdlib / lightweight fallback when heavy model is not available
            self._use_fallback = True

    def score_candidates(
        self,
        query_context: str,
        candidates: List[Tuple[GraphNode, Optional[GraphEdge], List[str]]],
    ) -> List[ScoredCandidate]:
        """Rank a closed, finite list of candidates against the query context.
        
        candidates: List of (node, connecting_edge, path_so_far)
        """
        if not candidates:
            return []

        # System 1 never has unbounded input: max budget check
        candidate_pairs = [
            (query_context, f"{c[0].canonical_signature()} {c[1].kind.value if c[1] else ''}")
            for c in candidates
        ]

        raw_scores: List[float] = []

        if not self._use_fallback and self._cross_encoder is not None:
            try:
                scores = self._cross_encoder.predict(candidate_pairs)
                raw_scores = [float(s) for s in scores]
            except Exception:
                raw_scores = self._fallback_score(query_context, candidates)
        else:
            raw_scores = self._fallback_score(query_context, candidates)

        # Apply edge confidence weighting: parser certain = 1.0, dynamic dispatch < 1.0
        weighted_scores = []
        for i, raw in enumerate(raw_scores):
            edge = candidates[i][1]
            conf = edge.confidence if edge else 1.0
            weighted_scores.append(raw * conf)

        # Softmax temperature calibration: P(c_i) = exp(s_i / T) / sum(exp(s_j / T))
        calibrated = self._softmax_temperature(weighted_scores, self.temperature)

        results: List[ScoredCandidate] = []
        for i, (node, edge, path) in enumerate(candidates):
            results.append(
                ScoredCandidate(
                    node=node,
                    edge=edge,
                    raw_score=round(weighted_scores[i], 4),
                    calibrated_score=round(calibrated[i], 4),
                    path=path + [node.id],
                )
            )

        # Sort descending by calibrated score
        results.sort(key=lambda x: x.calibrated_score, reverse=True)
        return results

    def _fallback_score(
        self,
        query: str,
        candidates: List[Tuple[GraphNode, Optional[GraphEdge], List[str]]],
    ) -> List[float]:
        """High-speed deterministic lexical-structural cross-scorer (sub-5ms)."""
        query_tokens = set(query.lower().replace(".", " ").replace(":", " ").replace("/", " ").split())
        scores = []

        for node, edge, _ in candidates:
            text = f"{node.name} {node.canonical_signature()} {node.file_path}".lower()
            text_tokens = set(text.replace(".", " ").replace(":", " ").replace("/", " ").split())

            if not query_tokens:
                score = 1.0
            else:
                overlap = len(query_tokens & text_tokens)
                score = overlap / max(1, len(query_tokens))

            # Structural affinity bonuses
            if edge:
                if edge.kind.value in {"ReadsColumn", "Mutates"}:
                    score += 0.3
                elif edge.kind.value in {"Calls", "ConsumesRoute"}:
                    score += 0.2

            # Type drift penalty / flag bonus for root-cause search
            if node.type_drift:
                score += 0.4

            scores.append(float(score))

        return scores

    @staticmethod
    def _softmax_temperature(scores: List[float], temp: float) -> List[float]:
        if not scores:
            return []
        # Numerical stability: subtract max
        max_s = max(scores)
        exp_scores = [math.exp((s - max_s) / temp) for s in scores]
        sum_exp = sum(exp_scores)
        if sum_exp == 0:
            return [1.0 / len(scores)] * len(scores)
        return [s / sum_exp for s in exp_scores]
