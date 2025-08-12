from io import BytesIO
from typing import Tuple

from PIL import Image, ImageSequence


def resize_and_pad_webp_bytes(image_bytes: bytes, size: Tuple[int, int] = (512, 512)) -> bytes:
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

            output = BytesIO()
            frames[0].save(
                output,
                format="WEBP",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=loop,
                lossless=True,
                method=6,
                minimize_size=True,
            )
            return output.getvalue()
        else:
            # Static frame path
            frame_rgba = image.convert("RGBA")
            frame_rgba.thumbnail(size, Image.LANCZOS)

            canvas = Image.new("RGBA", size, (0, 0, 0, 0))
            x_offset = (size[0] - frame_rgba.width) // 2
            y_offset = (size[1] - frame_rgba.height) // 2
            canvas.paste(frame_rgba, (x_offset, y_offset), frame_rgba)

            output = BytesIO()
            canvas.save(output, format="WEBP", lossless=True, method=6)
            return output.getvalue()


