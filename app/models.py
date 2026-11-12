from sqlalchemy import create_engine, Column, String, Integer, JSON, Enum, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import enum

Base = declarative_base()

class NotificationStatus(enum.Enum):
    accepted = "accepted"
    queued = "queued"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    enqueue_failed = "enqueue_failed"

class Notification(Base):
    __tablename__ = 'notifications'

    send_id = Column(String, primary_key=True, index=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    source = Column(String)
    channel = Column(Enum(NotificationStatus))
    recipient = Column(String)
    request_payload = Column(JSON)
    status = Column(Enum(NotificationStatus))
    provider_message_id = Column(String)
    attempt_count = Column(Integer, default=0)
    reference_id = Column(String, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

DATABASE_URL = "postgresql://user:password@localhost/dbname"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)
