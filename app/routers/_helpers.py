from fastapi.responses import Response


def attachment_response(content: bytes, media_type: str, filename: str) -> Response:
    """Download response with the filename stripped of characters that would let
    it break out of the Content-Disposition header."""
    safe_name = filename.replace("\r", "").replace("\n", "").replace('"', "")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
