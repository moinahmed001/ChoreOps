# File: helpers/user_image.py
"""User profile image handling for ChoreOps.

Responsibilities:
- Resolve the per-entry media directory and the servable URL for a stored image.
- Downscale and persist an uploaded image to <=512x512 px (``USER_IMAGE_MAX_EDGE``).
- Delete a stored image.

Design notes:
- Images are stored on disk (under the HA storage dir), never as blobs in the
  JSON store. The user record keeps only the relative filename
  (``DATA_USER_IMAGE_PATH``).
- All functions here perform blocking disk / Pillow work and MUST be called from
  an executor (``hass.async_add_executor_job``), except the pure path/URL helpers
  which are cheap and side-effect free.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant

from .. import const


def get_entry_media_dir(hass: HomeAssistant, entry_id: str) -> Path:
    """Return the on-disk directory for a config entry's user images.

    Example: <config>/.storage/choreops_media/<entry_id>/
    """
    return Path(
        hass.config.path(
            ".storage",
            const.USER_IMAGE_STORAGE_SUBDIR,
            entry_id,
        )
    )


def build_image_url(entry_id: str, filename: str | None) -> str:
    """Return the servable URL for a stored image filename, or "" if unset."""
    if not filename:
        return ""
    return f"{const.USER_IMAGE_URL_PREFIX}/{entry_id}/{filename}"


# ==============================================================================
# Generic primitives (shared by the user- and chore-image features)
# ==============================================================================


def save_resized_image_as(
    hass: HomeAssistant,
    entry_id: str,
    filename: str,
    source_path: str | Path,
    max_edge: int,
) -> str:
    """Downscale an uploaded image to <=``max_edge`` and store it under ``filename``.

    Blocking: opens the source with Pillow, resizes preserving aspect ratio so
    the longest edge is at most ``max_edge``, writes a normalized PNG into the
    entry media dir, and returns the stored relative filename.

    Must run in an executor.

    Raises:
        ValueError: If the source is not a readable/valid image.
    """
    # Imported lazily: Pillow is a declared requirement installed at runtime by
    # Home Assistant, and keeping the import local avoids a hard import at module
    # load for environments (e.g. some tooling) without it installed.
    from PIL import Image, UnidentifiedImageError

    media_dir = get_entry_media_dir(hass, entry_id)
    media_dir.mkdir(parents=True, exist_ok=True)
    dest = media_dir / filename

    try:
        with Image.open(source_path) as img:
            img = img.convert("RGBA")
            if img.width > max_edge or img.height > max_edge:
                # thumbnail() preserves aspect ratio and only shrinks.
                img.thumbnail((max_edge, max_edge), Image.LANCZOS)
            img.save(dest, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as err:
        raise ValueError(f"Invalid or unreadable image upload: {err}") from err

    return filename


def process_upload_as(
    hass: HomeAssistant,
    entry_id: str,
    filename: str,
    upload_id: str,
    max_edge: int,
) -> str:
    """Consume a FileSelector upload id, resize to ``max_edge``, store as ``filename``.

    Wraps HA's ``process_uploaded_file`` (a sync context manager that yields the
    temp upload path and removes it on exit) with the resize/persist step.

    Blocking: must run in an executor.

    Raises:
        ValueError: If the upload id is unknown or the file is not a valid image.
    """
    from homeassistant.components.file_upload import process_uploaded_file

    try:
        with process_uploaded_file(hass, upload_id) as source_path:
            return save_resized_image_as(
                hass, entry_id, filename, source_path, max_edge
            )
    except ValueError:
        raise
    except (KeyError, OSError) as err:
        raise ValueError(f"Could not process uploaded image: {err}") from err


async def async_resolve_image_field_generic(
    hass: HomeAssistant,
    entry_id: str,
    input_key: str,
    filename: str,
    payload: dict,
    max_edge: int,
) -> None:
    """Resolve a FileSelector upload field on a form payload in place.

    ``payload[input_key]`` holds a FileSelector upload id when the admin picked a
    file, otherwise absent/empty. When present, the file is resized/stored in an
    executor under ``filename`` and the field value is replaced with the stored
    relative filename so the record builder persists it. When absent, the key is
    removed so an edit preserves the existing image.

    Raises:
        ValueError: If the upload cannot be processed (surfaced as a form error).
    """
    raw = payload.get(input_key)
    if not raw:
        # No new upload: never let an empty value overwrite the stored path.
        payload.pop(input_key, None)
        return

    # FileSelector yields a single upload id (string) or a list of ids.
    upload_id = raw[0] if isinstance(raw, list) else raw
    stored = await hass.async_add_executor_job(
        process_upload_as, hass, entry_id, filename, upload_id, max_edge
    )
    payload[input_key] = stored


# ==============================================================================
# User-image wrappers
# ==============================================================================


def save_resized_image(
    hass: HomeAssistant,
    entry_id: str,
    user_id: str,
    source_path: str | Path,
) -> str:
    """Downscale an uploaded user image to <=512x512 and store it. Executor only."""
    return save_resized_image_as(
        hass, entry_id, f"{user_id}.png", source_path, const.USER_IMAGE_MAX_EDGE
    )


def process_upload_to_stored_image(
    hass: HomeAssistant,
    entry_id: str,
    user_id: str,
    upload_id: str,
) -> str:
    """Consume a user-image upload id, resize, and store it. Executor only."""
    return process_upload_as(
        hass, entry_id, f"{user_id}.png", upload_id, const.USER_IMAGE_MAX_EDGE
    )


async def async_resolve_image_field(
    hass: HomeAssistant,
    entry_id: str,
    user_id: str,
    user_input: dict,
) -> None:
    """Resolve the user image upload field (``CFOF_USERS_INPUT_IMAGE``) in place."""
    await async_resolve_image_field_generic(
        hass,
        entry_id,
        const.CFOF_USERS_INPUT_IMAGE,
        f"{user_id}.png",
        user_input,
        const.USER_IMAGE_MAX_EDGE,
    )


def delete_image(hass: HomeAssistant, entry_id: str, filename: str | None) -> None:
    """Delete a stored user image if present. Blocking; run in an executor."""
    if not filename:
        return
    target = get_entry_media_dir(hass, entry_id) / filename
    try:
        target.unlink(missing_ok=True)
    except OSError as err:
        const.LOGGER.warning(
            "Failed to delete user image %s for entry %s: %s",
            filename,
            entry_id,
            err,
        )
