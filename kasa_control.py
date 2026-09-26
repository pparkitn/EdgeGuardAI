"""Kasa smart plug controller (MQTT command consumer).

Subscribes to ``<topic>/command/plug/<name>`` and drives TP-Link
Kasa plugs via python-kasa; publishes state back to
``<topic>/status/plug/<name>``.

    python -m kasa_control

Payloads: plain ``on`` / ``off`` / ``toggle`` / ``state``, or JSON
``{"action": "on"}``.

Config: config.yaml -> kasa.plugs (name, host, optional child_id for
multi-outlet devices).
"""

import asyncio
import json
import logging

import paho.mqtt.client as mqtt

from edgeguard_config import get, get_int

logger = logging.getLogger(__name__)

MQTT_HOST = get(
    "broker",
    "host",
    default="JETSON_IP",
)

MQTT_PORT = get_int(
    "broker",
    "port",
    default=1883,
)

MQTT_TOPIC_PREFIX = get(
    "broker",
    "topic_prefix",
    default="edgeguard",
)

PLUGS = get(
    "kasa",
    "plugs",
    default=[],
)

VALID_ACTIONS = (
    "on",
    "off",
    "toggle",
    "state",
)


def parse_action(payload: str):

    """Normalize an MQTT payload to a plug action or None."""

    try:

        data = json.loads(payload)

    except (json.JSONDecodeError, TypeError):

        data = payload

    if isinstance(data, dict):

        action = data.get("action")

    else:

        action = data

    if isinstance(action, str):

        action = action.strip().lower()

    if action in VALID_ACTIONS:

        return action

    return None


async def _apply_action(plug_cfg: dict, action: str):

    from kasa import Device

    device = await Device.connect(
        host=plug_cfg["host"]
    )

    child_id = plug_cfg.get("child_id")

    if child_id:

        target = None

        for child in device.children:

            if child.device_id == child_id:

                target = child

                break

        if target is None:

            return None, "child not found"

    else:

        target = device

    if action == "on":

        await target.turn_on()

    elif action == "off":

        await target.turn_off()

    elif action == "toggle":

        if target.is_on:

            await target.turn_off()

        else:

            await target.turn_on()

    await device.update()

    return bool(target.is_on), None


class KasaController:

    def __init__(self):

        self.plugs = {
            plug.get("name"): plug
            for plug in PLUGS
            if plug.get("name")
        }

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2
        )

        self.client.on_connect = self._on_connect

        self.client.on_message = self._on_message

        self.running = True

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ):

        if reason_code == 0:

            logger.info(
                "Connected to MQTT broker at %s:%s",
                MQTT_HOST,
                MQTT_PORT,
            )

            topic = (
                f"{MQTT_TOPIC_PREFIX}/command/plug/#"
            )

            client.subscribe(topic, qos=1)

            logger.info(
                "Subscribed to %s",
                topic,
            )

            for name in self.plugs:

                self.report(name)

    def _on_message(
        self,
        client,
        userdata,
        message,
    ):

        name = message.topic.rsplit("/", 1)[-1]

        if name not in self.plugs:

            logger.warning(
                "No plug named %r",
                name,
            )

            return

        action = parse_action(
            message.payload.decode("utf-8")
        )

        if action is None:

            logger.warning(
                "Unrecognized command for %s: %r",
                name,
                message.payload,
            )

            return

        logger.info(
            "Command %s -> %s",
            action,
            name,
        )

        state, error = asyncio.run(
            _apply_action(
                self.plugs[name],
                action,
            )
        )

        self._publish_status(
            name,
            state,
            error,
        )

    def _publish_status(
        self,
        name,
        state,
        error=None,
    ):

        payload = {
            "name": name,
            "state": state,
            "ok": error is None,
        }

        if error:

            payload["error"] = error

        topic = (
            f"{MQTT_TOPIC_PREFIX}/status/plug/{name}"
        )

        self.client.publish(
            topic,
            json.dumps(payload),
            qos=1,
        )

        logger.info(
            "Status %s -> %s",
            name,
            payload,
        )

    def report(self, name: str):

        plug = self.plugs.get(name)

        if plug is None:

            return

        try:

            state, error = asyncio.run(
                _apply_action(plug, "state")
            )

        except Exception as exc:

            logger.exception(
                "Status poll failed for %s",
                name,
            )

            self._publish_status(
                name,
                None,
                str(exc),
            )

            return

        self._publish_status(
            name,
            state,
            error,
        )

    def start(self):

        if not self.plugs:

            logger.warning(
                "No Kasa plugs configured "
                "(config.yaml -> kasa.plugs)"
            )

        self.client.connect_async(
            MQTT_HOST,
            MQTT_PORT,
        )

        self.client.loop_start()

    def stop(self):

        self.client.loop_stop()

        self.client.disconnect()

        self.running = False


def main():

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)-7s "
            "%(name)s: %(message)s"
        ),
    )

    controller = KasaController()

    controller.start()

    import time

    try:

        while controller.running:

            time.sleep(1)

    except KeyboardInterrupt:

        pass

    finally:

        controller.stop()


if __name__ == "__main__":

    main()