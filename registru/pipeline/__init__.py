"""Pașii pipeline-ului: extract -> normalize -> classify -> build."""

from registru.pipeline.build import build, read_interim, write_interim
from registru.pipeline.classify import classify, score_row

__all__ = ["build", "classify", "read_interim", "score_row", "write_interim"]
