from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable


MessageHandler = Callable[..., None]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Subscription:
    topic: str
    token: int


class MessageBroker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_token = 1
        self._subscribers: dict[str, dict[int, MessageHandler]] = {}

    def subscribe(self, topic: str, handler: MessageHandler) -> Subscription:
        if not topic:
            raise ValueError("topic cannot be empty")
        if not callable(handler):
            raise TypeError("handler must be callable")

        with self._lock:
            token = self._next_token
            self._next_token += 1
            topic_handlers = self._subscribers.setdefault(topic, {})
            topic_handlers[token] = handler
        return Subscription(topic=topic, token=token)

    def unsubscribe(self, subscription: Subscription | None) -> None:
        if subscription is None:
            return

        with self._lock:
            topic_handlers = self._subscribers.get(subscription.topic)
            if not topic_handlers:
                return
            topic_handlers.pop(subscription.token, None)
            if not topic_handlers:
                self._subscribers.pop(subscription.topic, None)

    def publish(self, topic: str, **payload: Any) -> None:

        if not topic:
            raise ValueError("borker's topic cannot be empty")

        with self._lock:
            handlers = list(self._subscribers.get(topic, {}).values())

        for handler in handlers:
            try:
                handler(**payload)
            except Exception:
                logger.exception("broker handler failed for topic %s", topic)

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()


def create_broker() -> MessageBroker:
    return MessageBroker()
