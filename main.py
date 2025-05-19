import os
import re

from fastapi import FastAPI, Query
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import WebshareProxyConfig

app = FastAPI()


def extract_video_id(url: str) -> str | None:
    """
    Extracts video ID from YouTube URL.
    Handles standard, short, and embed URLs.
    """
    patterns = [
        r"(?:v=|\/videos\/|embed\/|youtu.be\/|\/v\/|\/e\/|watch\?v=|\&v=)([^#\&\?]*).*",
        r"(?:youtube.com\/shorts\/)([^#\&\?]*).*",
        r"(?:youtube.com\/live\/)([^#\&\?]*).*",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


@app.get("/transcript")
async def get_transcript(url: str = Query(..., description="The YouTube video URL")):
    video_id = extract_video_id(url)

    if not video_id:
        return {
            "success": False,
            "fail_reason": "invalid_url",
            "language": None,
            "transcript": None,
        }

    ytt_api = YouTubeTranscriptApi()
    # Get Webshare credentials from environment variables
    proxy_username = os.getenv("WEBSHARE_USERNAME")
    proxy_password = os.getenv("WEBSHARE_PASSWORD")

    if proxy_username and proxy_password:
        ytt_api = YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(
                proxy_username=proxy_username,
                proxy_password=proxy_password,
            )
        )
    else:
        # Optionally, handle the case where proxy credentials are not set.
        # For now, it will proceed without a proxy if they are not found.
        # Consider logging a warning or raising an error if proxy is mandatory.
        print(
            "Warning: WEBSHARE_USERNAME or WEBSHARE_PASSWORD not set. Proceeding without proxy."
        )
        ytt_api = YouTubeTranscriptApi()

    try:
        transcript_list = ytt_api.list_transcripts(video_id)

        # Try to find a manually created transcript in preferred languages first
        # User did not specify preferred languages, so we'll try common ones or any available.
        # For simplicity, let's try to get any manually created transcript first.
        # Then any generated one.

        found_transcript = None
        language_code = None
        is_generated = False

        # Attempt to find any manually created transcript
        try:
            manual_transcripts = [t for t in transcript_list if not t.is_generated]
            if manual_transcripts:
                # Pick the first available manual transcript (often English or original language)
                # Or we could try to find specific languages like 'en' first if needed
                # For now, let's try 'en' specifically, then the first one available.
                english_manual = next(
                    (t for t in manual_transcripts if t.language_code == "en"), None
                )
                if english_manual:
                    found_transcript = english_manual.fetch()
                    language_code = "en"
                    is_generated = False
                else:
                    # If no English manual, take the first available manual one
                    transcript_to_fetch = manual_transcripts[0]
                    found_transcript = transcript_to_fetch.fetch()
                    language_code = transcript_to_fetch.language_code
                    is_generated = False
        except Exception:  # Broad exception as find_manually_created_transcript might not exist or raise
            pass

        if not found_transcript:
            # If no manual transcript, try to find any auto-generated transcript
            try:
                generated_transcripts = [t for t in transcript_list if t.is_generated]
                if generated_transcripts:
                    # Try 'en' auto-generated first
                    english_generated = next(
                        (t for t in generated_transcripts if t.language_code == "en"),
                        None,
                    )
                    if english_generated:
                        found_transcript = english_generated.fetch()
                        language_code = "en_generated"
                        is_generated = True
                    else:
                        # If no English generated, take the first available generated one
                        transcript_to_fetch = generated_transcripts[0]
                        found_transcript = transcript_to_fetch.fetch()
                        language_code = f"{transcript_to_fetch.language_code}_generated"
                        is_generated = True
            except Exception:
                pass

        if found_transcript:
            transcript_text = " ".join([item["text"] for item in found_transcript])
            final_language_code = language_code
            if is_generated and not language_code.endswith("_generated"):
                final_language_code = f"{language_code}_generated"
            elif not is_generated and language_code.endswith(
                "_generated"
            ):  # Should not happen based on logic
                final_language_code = language_code.replace("_generated", "")

            return {
                "success": True,
                "fail_reason": None,
                "language": final_language_code,
                "transcript": transcript_text,
            }
        else:
            # This case implies transcript_list was empty or no suitable transcript found
            return {
                "success": False,
                "fail_reason": "no_transcript_available",
                "language": None,
                "transcript": None,
            }

    except TranscriptsDisabled:
        return {
            "success": False,
            "fail_reason": "transcripts_disabled",
            "language": None,
            "transcript": None,
        }
    except NoTranscriptFound:
        # This exception is more specific for when no transcript is found for specific languages.
        # The logic above tries to be more exhaustive.
        return {
            "success": False,
            "fail_reason": "no_transcript_found_for_video",
            "language": None,
            "transcript": None,
        }
    except Exception as e:
        # Catch-all for other potential errors from the API or logic
        return {
            "success": False,
            "fail_reason": f"other: {str(e)}",
            "language": None,
            "transcript": None,
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
