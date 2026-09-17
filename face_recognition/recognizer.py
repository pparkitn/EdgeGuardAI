import numpy as np


class FaceRecognizer:

    def __init__(
        self,
        database,
        threshold=0.55,
    ):

        self.database = database
        self.threshold = threshold

    @staticmethod
    def cosine_similarity(a, b):

        a = np.asarray(a)
        b = np.asarray(b)

        denominator = (
            np.linalg.norm(a)
            * np.linalg.norm(b)
        )

        if denominator == 0:
            return 0.0

        return float(
            np.dot(a, b) / denominator
        )

    def recognize(self, embedding):

        best_name = "Unknown"
        best_score = 0.0

        for name, embeddings in self.database.get_people().items():

            for stored_embedding in embeddings:

                score = self.cosine_similarity(
                    embedding,
                    stored_embedding,
                )

                if score > best_score:
                    best_score = score
                    best_name = name

        if best_score < self.threshold:
            best_name = "Unknown"

        return best_name, best_score