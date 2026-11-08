# File: helpers/chore_image.py
"""Chore image handling for ChoreOps.

Thin wrappers over the generic image primitives in ``user_image`` that store a
per-chore photo (downscaled to <=100x100, ``CHORE_IMAGE_MAX_EDGE``) in the same
per-entry media dir served at ``/choreops_media/<entry_id>/``. Chore files are
namespaced ``chore_<id>.png`` so they never collide with user images
(``<user_id>.png``).

The chore record stores only the relative filename (``DATA_CHORE_IMAGE_PATH``);
the binary lives on disk, never in the JSON store.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .. import const
from . import user_image

# Reuse the shared URL builder and media-dir resolution.
build_image_url = user_image.build_image_url


def _chore_filename(chore_id: str) -> str:
    """Return the deterministic stored filename for a chore image."""
    return f"chore_{chore_id}.png"


async def async_resolve_image_field(
    hass: HomeAssistant,
    entry_id: str,
    chore_id: str,
    chore_input: dict,
) -> None:
    """Resolve the chore image upload field (``CFOF_CHORES_INPUT_IMAGE``) in place.

    On a new upload: resize to 100x100 and replace the field value with the
    stored filename. On omit: drop the key so an edit preserves the existing
    image.

    Raises:
        ValueError: If the upload cannot be processed (surfaced as a form error).
    """
    await user_image.async_resolve_image_field_generic(
        hass,
        entry_id,
        const.CFOF_CHORES_INPUT_IMAGE,
        _chore_filename(chore_id),
        chore_input,
        const.CHORE_IMAGE_MAX_EDGE,
    )


def delete_image(hass: HomeAssistant, entry_id: str, filename: str | None) -> None:
    """Delete a stored chore image if present. Blocking; run in an executor."""
    user_image.delete_image(hass, entry_id, filename)
