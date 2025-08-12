from io import BytesIO
from typing import Tuple, List

from PIL import Image, ImageSequence


def _encode_animated_webp(
    frames: List[Image.Image],
    durations: List[int],
    loop: int,
    quality: int,
    lossless: bool,
    minimize_size: bool = True,
):
    output = BytesIO()
    frames[0].save(
        output,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        quality=quality,
        lossless=lossless,
        method=6,
        minimize_size=minimize_size,
    )
    return output.getvalue()


def _encode_static_webp(
    image: Image.Image,
    quality: int,
    lossless: bool,
    minimize_size: bool = True,
):
    output = BytesIO()
    image.save(
        output,
        format="WEBP",
        quality=quality,
        lossless=lossless,
        method=6,
        minimize_size=minimize_size,
    )
    return output.getvalue()


def resize_and_pad_webp_bytes(
    image_bytes: bytes,
    size: Tuple[int, int] = (512, 512),
    max_bytes: int | None = None,
) -> bytes:
    """
    Resize a WebP image (animated or static) to fit within `size`,
    maintaining aspect ratio and padding onto a transparent canvas of `size`.

    Returns the processed image as WebP bytes. For animations, preserves frames,
    per-frame durations, loop count, and transparency.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        is_animated = getattr(image, "is_animated", False)

        if is_animated and getattr(image, "n_frames", 1) > 1:
            frames = []
            durations = []
            loop = image.info.get("loop", 0)

            for frame in ImageSequence.Iterator(image):
                frame_rgba = frame.convert("RGBA")
                # Resize while preserving aspect
                frame_rgba.thumbnail(size, Image.LANCZOS)

                # Center on transparent canvas
                canvas = Image.new("RGBA", size, (0, 0, 0, 0))
                x_offset = (size[0] - frame_rgba.width) // 2
                y_offset = (size[1] - frame_rgba.height) // 2
                canvas.paste(frame_rgba, (x_offset, y_offset), frame_rgba)

                frames.append(canvas)
                # Prefer per-frame duration if provided
                durations.append(frame.info.get("duration", image.info.get("duration", 100)))

            # Try progressively lower qualities to meet max_bytes if provided
            if max_bytes is None:
                return _encode_animated_webp(
                    frames=frames,
                    durations=durations,
                    loop=loop,
                    quality=80,
                    lossless=False,
                )

            for quality in [80, 70, 60, 50, 40, 35, 30, 25, 20]:
                encoded = _encode_animated_webp(
                    frames=frames,
                    durations=durations,
                    loop=loop,
                    quality=quality,
                    lossless=False,
                )
                if len(encoded) <= max_bytes:
                    return encoded

            # Last resort: still return the smallest we got (lowest quality)
            return encoded
        else:
            # Static frame path
            frame_rgba = image.convert("RGBA")
            frame_rgba.thumbnail(size, Image.LANCZOS)

            canvas = Image.new("RGBA", size, (0, 0, 0, 0))
            x_offset = (size[0] - frame_rgba.width) // 2
            y_offset = (size[1] - frame_rgba.height) // 2
            canvas.paste(frame_rgba, (x_offset, y_offset), frame_rgba)

            if max_bytes is None:
                return _encode_static_webp(canvas, quality=90, lossless=False)

            # Try qualities for static as well
            for quality in [95, 90, 85, 80, 70, 60, 50, 40]:
                encoded = _encode_static_webp(canvas, quality=quality, lossless=False)
                if len(encoded) <= max_bytes:
                    return encoded

            return encoded


