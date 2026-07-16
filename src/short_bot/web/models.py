"""SQLAlchemy ORM models that map onto Phase 1's SQLite schema.

These tables already exist (created by `short_bot.db.init_db()`). The ORM
classes here are read/write mappings — `db.create_all()` is a no-op since
the schema is identical.
"""
from datetime import datetime, timezone
from pathlib import Path

from short_bot.web.extensions import db


class ProcessedItem(db.Model):
    __tablename__ = "processed_items"
    guid = db.Column(db.String, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String, nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)


class RssItem(db.Model):
    __tablename__ = "rss_items"
    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String, nullable=False)
    channel = db.Column(db.String, nullable=False)
    title = db.Column(db.Text, nullable=False)
    link = db.Column(db.Text, nullable=False)
    source = db.Column(db.String)
    pub_date = db.Column(db.DateTime)
    thumb_url = db.Column(db.Text)
    score = db.Column(db.Float)
    status = db.Column(db.String)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    short_id = db.Column(db.Integer, db.ForeignKey("shorts.id"))


class Short(db.Model):
    __tablename__ = "shorts"
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String, nullable=False)
    rss_item_guid = db.Column(db.String)
    title = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.Text, nullable=False)
    duration_s = db.Column(db.Integer)
    script_json = db.Column(db.Text)
    render_ms = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    deleted_at = db.Column(db.DateTime)

    @property
    def file_url(self) -> str:
        """Canonical URL the panel uses to serve the mp4."""
        return f"/output/{self.channel}/{Path(self.file_path).name}"


class Run(db.Model):
    __tablename__ = "runs"
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String, nullable=False)
    trigger = db.Column(db.String, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    status = db.Column(db.String)
    short_id = db.Column(db.Integer, db.ForeignKey("shorts.id"))
    error = db.Column(db.Text)
    log_path = db.Column(db.Text)

    @property
    def duration_seconds(self) -> int | None:
        """Wall-clock seconds between start and end. Tolerates rows where one
        timestamp is tz-aware (recent inserts) and the other is tz-naive
        (older inserts) by treating naive as UTC."""
        if self.started_at is None or self.ended_at is None:
            return None
        s = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=timezone.utc)
        e = self.ended_at if self.ended_at.tzinfo else self.ended_at.replace(tzinfo=timezone.utc)
        return int((e - s).total_seconds())


class YoutubeUpload(db.Model):
    __tablename__ = "youtube_uploads"
    id = db.Column(db.Integer, primary_key=True)
    short_id = db.Column(db.Integer, db.ForeignKey("shorts.id"), nullable=False)
    video_id = db.Column(db.String)
    video_url = db.Column(db.String)
    status = db.Column(db.String, nullable=False)
    error = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class YoutubeVideoStats(db.Model):
    __tablename__ = "youtube_video_stats"
    video_id = db.Column(db.String, primary_key=True)
    snapshot_date = db.Column(db.String, primary_key=True)
    views = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    comments = db.Column(db.Integer, default=0)
    watch_time_min = db.Column(db.Float, default=0.0)
    avg_view_duration_s = db.Column(db.Float, default=0.0)
    subscribers_gained = db.Column(db.Integer, default=0)
    avg_view_percentage = db.Column(db.Float, default=0.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class YoutubeChannelStats(db.Model):
    __tablename__ = "youtube_channel_stats"
    channel = db.Column(db.String, primary_key=True)
    snapshot_date = db.Column(db.String, primary_key=True)
    subscribers = db.Column(db.Integer, default=0)
    total_views = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class YoutubeQuota(db.Model):
    __tablename__ = "youtube_quota"
    channel = db.Column(db.String, primary_key=True)
    date = db.Column(db.String, primary_key=True)
    units_used = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
