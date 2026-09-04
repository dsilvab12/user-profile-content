import re
from datetime import datetime, timedelta, timezone

from app.models import DatabricksAudienceRequest, GuestListEventRequest


MAX_DAY_BUCKET = 91
OUTPUT_TABLE_PREFIX = "sandbox_prod.bdsilva"


class EventTransformer:
    def transform(self, payload: GuestListEventRequest) -> DatabricksAudienceRequest:
        event_date = _as_utc(payload.event_date)
        artist_table_name = normalize_artist_name(payload.artist.name)

        return DatabricksAudienceRequest(
            request_id=payload.event_id,
            artist_name=payload.artist.name,
            channel_names=[payload.channel.name],
            start_date=event_date.date().isoformat(),
            end_date=(event_date - timedelta(days=MAX_DAY_BUCKET)).date().isoformat(),
            max_day_bucket=MAX_DAY_BUCKET,
            output_table=f"{OUTPUT_TABLE_PREFIX}.{artist_table_name}_channel_results",
        )


def normalize_artist_name(artist_name: str) -> str:
    normalized = artist_name.lower()
    normalized = normalized.replace("'", "").replace("’", "")
    normalized = re.sub(r"[\s/]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

