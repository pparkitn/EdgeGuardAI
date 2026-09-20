"""Minimal Face container, API-compatible with insightface's Face."""

import numpy as np


class Face(dict):

    """A detected face with bbox, landmarks and (optional) embedding.

    Mirrors `insightface.app.common.Face` so the shared components
    (camera agents, recognizer) work unchanged with GPU detection.
    """

    def __init__(self, d=None, **kwargs):

        if d is None:
            d = {}

        if kwargs:
            d.update(kwargs)

        for key, value in d.items():
            setattr(self, key, value)

    def __setattr__(self, name, value):

        super().__setattr__(name, value)

        super().__setitem__(name, value)

    __setitem__ = __setattr__

    def __getattr__(self, name):

        return None

    @property
    def normed_embedding(self):

        if self.embedding is None:
            return None

        norm = np.linalg.norm(self.embedding)

        if norm == 0:
            return None

        return self.embedding / norm