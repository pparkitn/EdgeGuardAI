from .config import CAMERA_LOCATIONS, TEMPLATES


def location_label(camera_id: str) -> str:

    if camera_id is None:
        return "the camera"

    return CAMERA_LOCATIONS.get(
        camera_id,
        f"the {camera_id.replace('_', ' ')}",
    )


def build_announcement(event: dict):

    event_type = event.get("event_type")

    template = TEMPLATES.get(event_type)

    if template is None:
        return None

    try:

        text = template.format(
            location=location_label(
                event.get("camera_id")
            ),
            person_id=event.get(
                "person_id",
                "our guest",
            ),
        )

    except KeyError:

        text = template

    return text