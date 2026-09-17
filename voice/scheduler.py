import logging
import threading
import time

import schedule

from .config import SCHEDULED_MESSAGES

logger = logging.getLogger("voice.scheduler")

WEEKDAYS = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
    "monday": "monday",
    "tuesday": "tuesday",
    "wednesday": "wednesday",
    "thursday": "thursday",
    "friday": "friday",
    "saturday": "saturday",
    "sunday": "sunday",
}


class Scheduler:

    """Fires scheduled announcements (daily, weekly, or interval-based).

    Every fired message goes through the same pipeline as security
    events: Polly synthesis (cached) -> DeliveryWorker -> both the
    local speaker and the Google Cast speakers.
    """

    def __init__(self, say):

        self.say = say

        self.thread = None

        self.running = False

    def load(self, definitions=None):

        for definition in definitions or SCHEDULED_MESSAGES:

            self.add(definition)

    def add(self, definition: dict):

        text = definition.get("text")

        when = definition.get("time")

        days = definition.get("days")

        every = definition.get("every")

        if text is None:
            logger.warning(
                "Scheduled message without text "
                "ignored: %s",
                definition,
            )
            return

        try:

            if every is not None:

                schedule.every(every).seconds.do(
                    self._fire,
                    text,
                    definition,
                )

                logger.info(
                    "Scheduled: every %s s -> %s",
                    every,
                    text,
                )

            elif days:

                for day in days:

                    day = WEEKDAYS.get(
                        day.lower(),
                        day.lower(),
                    )

                    getattr(
                        schedule.every(),
                        day,
                    ).at(when).do(
                        self._fire,
                        text,
                        definition,
                    )

                logger.info(
                    "Scheduled: %s at %s -> %s",
                    ", ".join(days),
                    when,
                    text,
                )

            else:

                schedule.every().day.at(
                    when
                ).do(
                    self._fire,
                    text,
                    definition,
                )

                logger.info(
                    "Scheduled: daily at %s -> %s",
                    when,
                    text,
                )

        except Exception:

            logger.exception(
                "Could not schedule: %s",
                definition,
            )

    def _fire(self, text, definition):

        logger.info(
            "Scheduled announcement fired: %s",
            text,
        )

        try:

            self.say(
                text,
                speakers=definition.get(
                    "speakers"
                ),
                local=definition.get(
                    "local",
                    True,
                ),
            )

        except Exception:

            logger.exception(
                "Scheduled announcement failed"
            )

    def start(self):

        if self.thread is not None:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._run,
            name="scheduler",
            daemon=True,
        )

        self.thread.start()

    def _run(self):

        while self.running:

            try:

                schedule.run_pending()

            except Exception:

                logger.exception(
                    "Scheduler tick failed"
                )

            time.sleep(1)

    def stop(self):

        self.running = False

        schedule.clear()