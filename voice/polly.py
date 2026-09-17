import logging

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
)

from .audio_cache import AudioCache
from .config import POLLY_REGION, POLLY_VOICE

logger = logging.getLogger(__name__)


class PollyClient:

    def __init__(
        self,
        region: str = POLLY_REGION,
        voice: str = POLLY_VOICE,
    ):

        self.voice = voice
        self.cache = AudioCache()

        try:

            self.client = boto3.client(
                "polly",
                region_name=region,
            )

        except Exception:

            logger.exception(
                "Failed to create Polly client "
                "(check AWS credentials)"
            )

            self.client = None

    def synthesize(self, text: str):

        if self.client is None:
            return None

        if self.cache.has(text):

            logger.info(
                "Audio cache hit for text "
                "(hash %s)",
                self.cache.filename_for(text),
            )

            return self.cache.path_for(text)

        try:

            response = self.client.synthesize_speech(
                Text=text,
                OutputFormat="mp3",
                VoiceId=self.voice,
                Engine="neural",
            )

        except (BotoCoreError, ClientError) as exc:

            logger.error(
                "Polly synthesis failed: %s",
                exc,
            )

            return None

        stream = response.get("AudioStream")

        if stream is None:

            logger.error(
                "Polly response contained no audio"
            )

            return None

        try:

            path = self.cache.store(
                text,
                stream.read(),
            )

        except OSError:

            logger.exception(
                "Could not write audio cache file"
            )

            return None

        logger.info(
            "Synthesized audio -> %s",
            path,
        )

        return path