import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


TOKEN_RE = re.compile(r"(?:#\w+(?:-\w+)*)|\b\w+\b", re.UNICODE)
USER_ID_RE = re.compile(r"^user_[\w]{3,}$", re.IGNORECASE | re.UNICODE)

POSITIVE_WORDS = {
    "adorei",
    "gostei",
    "bom",
    "otimo",
    "excelente",
    "perfeito",
    "maravilhoso",
    "incrivel",
    "fantastico",
    "positivo",
    "top",
}
NEGATIVE_WORDS = {
    "ruim",
    "terrivel",
    "pessimo",
    "horrivel",
    "odiei",
    "detestei",
    "negativo",
    "pior",
}
INTENSIFIERS = {
    "muito",
    "super",
    "mega",
    "ultra",
    "extremamente",
    "bem",
    "bastante",
}
NEGATIONS = {
    "nao",
    "nunca",
    "jamais",
    "nem",
}

META_PHRASE = "teste tecnico mbras"
META_PHRASE_NORMALIZED = None


class ValidationError(Exception):
    def __init__(self, message: str, code: str = "INVALID_INPUT") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class BusinessRuleError(Exception):
    def __init__(self, message: str, code: str = "UNSUPPORTED_TIME_WINDOW") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class ParsedMessage:
    msg_id: str
    content: str
    timestamp: datetime
    user_id: str
    hashtags: List[str]
    reactions: int
    shares: int
    views: int


def normalize_for_matching(text: str) -> str:
    lowered = text.casefold()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _init_meta_phrase() -> str:
    return normalize_for_matching(META_PHRASE)


META_PHRASE_NORMALIZED = _init_meta_phrase()


def parse_timestamp(raw: str) -> datetime:
    if not isinstance(raw, str):
        raise ValidationError("Timestamp invalido", code="INVALID_TIMESTAMP")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", raw):
        raise ValidationError("Timestamp invalido", code="INVALID_TIMESTAMP")
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValidationError("Timestamp invalido", code="INVALID_TIMESTAMP") from exc
    return parsed.replace(tzinfo=timezone.utc)


def tokenize(content: str) -> List[str]:
    return TOKEN_RE.findall(content)


def is_meta_message(content: str) -> bool:
    normalized = normalize_for_matching(content.strip())
    return normalized == META_PHRASE_NORMALIZED


def has_candidate_awareness(content: str) -> bool:
    normalized = normalize_for_matching(content)
    return META_PHRASE_NORMALIZED in normalized


def is_special_pattern(content: str) -> bool:
    return len(content) == 42 and "mbras" in content.casefold()


def analyze_sentiment(content: str, mbras_employee: bool) -> Tuple[str, float, List[str]]:
    if is_meta_message(content):
        return "meta", 0.0, []

    tokens = tokenize(content)
    text_tokens = [tok for tok in tokens if not tok.startswith("#")]
    if not text_tokens:
        return "neutral", 0.0, text_tokens

    normalized_tokens = [normalize_for_matching(tok) for tok in text_tokens]
    negation_positions = {idx for idx, tok in enumerate(normalized_tokens) if tok in NEGATIONS}

    score_sum = 0.0
    intensifier_multiplier = 1.0

    for idx, tok in enumerate(normalized_tokens):
        if tok in INTENSIFIERS:
            intensifier_multiplier *= 1.5
            continue

        if tok in POSITIVE_WORDS or tok in NEGATIVE_WORDS:
            score = 1.0 if tok in POSITIVE_WORDS else -1.0

            if intensifier_multiplier != 1.0:
                score *= intensifier_multiplier
                intensifier_multiplier = 1.0

            neg_count = 0
            for neg_idx in negation_positions:
                if 0 < idx - neg_idx <= 3:
                    neg_count += 1
            if neg_count % 2 == 1:
                score *= -1.0

            if mbras_employee and score > 0:
                score *= 2.0

            score_sum += score

    sentiment_score = score_sum / len(text_tokens)
    if sentiment_score > 0.1:
        return "positive", sentiment_score, text_tokens
    if sentiment_score < -0.1:
        return "negative", sentiment_score, text_tokens
    return "neutral", sentiment_score, text_tokens


def _is_prime(number: int) -> bool:
    if number <= 1:
        return False
    if number <= 3:
        return True
    if number % 2 == 0 or number % 3 == 0:
        return False
    limit = int(math.sqrt(number)) + 1
    for i in range(5, limit, 6):
        if number % i == 0 or number % (i + 2) == 0:
            return False
    return True


def _next_prime(number: int) -> int:
    candidate = max(2, number)
    while not _is_prime(candidate):
        candidate += 1
    return candidate


def _followers_from_user_id(user_id: str) -> int:
    if len(user_id) == 13:
        return 233

    normalized_nfkd = unicodedata.normalize("NFKD", user_id)
    stripped = "".join(ch for ch in normalized_nfkd if not unicodedata.combining(ch))
    if stripped != user_id:
        return 4242

    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    followers = (int(digest, 16) % 10000) + 100

    if user_id.endswith("_prime"):
        followers = _next_prime(followers)

    return followers


def _validate_message(raw: Dict[str, Any]) -> ParsedMessage:
    if not isinstance(raw, dict):
        raise ValidationError("Mensagem invalida")

    msg_id = raw.get("id")
    content = raw.get("content")
    timestamp_raw = raw.get("timestamp")
    user_id = raw.get("user_id")

    if not isinstance(msg_id, str) or not msg_id:
        raise ValidationError("Campo 'id' invalido")
    if not isinstance(content, str):
        raise ValidationError("Campo 'content' invalido")
    if len(content) > 280:
        raise ValidationError("Campo 'content' excede 280 caracteres")
    if not isinstance(user_id, str) or not USER_ID_RE.match(user_id):
        raise ValidationError("Campo 'user_id' invalido")

    timestamp = parse_timestamp(timestamp_raw)

    hashtags = raw.get("hashtags", [])
    if hashtags is None:
        hashtags = []
    if not isinstance(hashtags, list):
        raise ValidationError("Campo 'hashtags' invalido")
    for tag in hashtags:
        if not isinstance(tag, str) or not tag.startswith("#"):
            raise ValidationError("Campo 'hashtags' invalido")

    reactions = raw.get("reactions", 0)
    shares = raw.get("shares", 0)
    views = raw.get("views", 0)
    for name, value in (("reactions", reactions), ("shares", shares), ("views", views)):
        if not isinstance(value, int) or value < 0:
            raise ValidationError(f"Campo '{name}' invalido")

    return ParsedMessage(
        msg_id=msg_id,
        content=content,
        timestamp=timestamp,
        user_id=user_id,
        hashtags=hashtags,
        reactions=reactions,
        shares=shares,
        views=views,
    )


def _validate_payload(payload: Any) -> Tuple[List[ParsedMessage], int]:
    if not isinstance(payload, dict):
        raise ValidationError("Payload invalido")

    time_window = payload.get("time_window_minutes")
    if not isinstance(time_window, int) or time_window <= 0:
        raise ValidationError("Campo 'time_window_minutes' invalido")
    if time_window == 123:
        raise BusinessRuleError(
            "Valor de janela temporal não suportado na versão atual",
            code="UNSUPPORTED_TIME_WINDOW",
        )

    messages_raw = payload.get("messages", [])
    if not isinstance(messages_raw, list):
        raise ValidationError("Campo 'messages' invalido")

    parsed_messages = [_validate_message(msg) for msg in messages_raw]
    return parsed_messages, time_window


def _sentiment_modifier(label: str) -> float:
    if label == "positive":
        return 1.2
    if label == "negative":
        return 0.8
    return 1.0


def _compute_trending(
    messages: Iterable[ParsedMessage],
    now_utc: datetime,
    sentiments: Dict[str, str],
) -> List[str]:
    trending: Dict[str, Dict[str, float]] = {}
    for msg in messages:
        if not msg.hashtags:
            continue
        minutes_since = (now_utc - msg.timestamp).total_seconds() / 60.0
        minutes_since = max(minutes_since, 1.0)
        weight_time = 1.0 + (1.0 / minutes_since)
        modifier = _sentiment_modifier(sentiments[msg.msg_id])
        for tag in msg.hashtags:
            weight = weight_time * modifier
            if len(tag) > 8:
                weight *= math.log10(len(tag)) / math.log10(8)
            data = trending.setdefault(tag, {"weight": 0.0, "count": 0.0, "sentiment": 0.0})
            data["weight"] += weight
            data["count"] += 1.0
            data["sentiment"] += modifier

    ranked = sorted(
        trending.items(),
        key=lambda item: (-item[1]["weight"], -item[1]["count"], -item[1]["sentiment"], item[0]),
    )
    return [tag for tag, _ in ranked[:5]]


def _detect_burst(user_timestamps: Dict[str, List[datetime]]) -> bool:
    window = timedelta(minutes=5)
    for timestamps in user_timestamps.values():
        if len(timestamps) <= 10:
            continue
        timestamps.sort()
        start = 0
        for end in range(len(timestamps)):
            while timestamps[end] - timestamps[start] > window:
                start += 1
            if end - start + 1 > 10:
                return True
    return False


def _detect_alternating(sentiment_sequences: Dict[str, List[Tuple[datetime, str]]]) -> bool:
    for sequence in sentiment_sequences.values():
        if len(sequence) < 10:
            continue
        sequence.sort(key=lambda item: item[0])
        streak = 1
        last_label = None
        for _, label in sequence:
            if label not in {"positive", "negative"}:
                streak = 1
                last_label = None
                continue
            if last_label is None:
                last_label = label
                streak = 1
                continue
            if label != last_label:
                streak += 1
                last_label = label
            else:
                streak = 1
                last_label = label
            if streak >= 10:
                return True
    return False


def _detect_synchronized(timestamps: List[datetime]) -> bool:
    if len(timestamps) < 3:
        return False
    timestamps.sort()
    start = 0
    max_window = timedelta(seconds=4)
    for end in range(len(timestamps)):
        while timestamps[end] - timestamps[start] > max_window:
            start += 1
        if end - start + 1 >= 3:
            return True
    return False


def analyze_feed(payload: Dict[str, Any]) -> Dict[str, Any]:
    messages, time_window = _validate_payload(payload)

    if messages:
        now_utc = max(msg.timestamp for msg in messages)
    else:
        now_utc = datetime.now(timezone.utc)

    window_start = now_utc - timedelta(minutes=time_window)
    filtered_messages = [
        msg
        for msg in messages
        if window_start <= msg.timestamp <= now_utc + timedelta(seconds=5)
    ]

    flags = {
        "mbras_employee": False,
        "special_pattern": False,
        "candidate_awareness": False,
    }

    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    sentiment_total = 0
    sentiments_by_id: Dict[str, str] = {}
    sentiment_sequences: Dict[str, List[Tuple[datetime, str]]] = {}
    user_timestamps: Dict[str, List[datetime]] = {}
    all_timestamps: List[datetime] = []

    user_stats: Dict[str, Dict[str, Any]] = {}
    total_interactions = 0
    total_views = 0

    for msg in filtered_messages:
        user_lower = msg.user_id.casefold()
        is_mbras_user = "mbras" in user_lower
        if is_mbras_user:
            flags["mbras_employee"] = True
        if is_special_pattern(msg.content):
            flags["special_pattern"] = True
        if has_candidate_awareness(msg.content):
            flags["candidate_awareness"] = True

        label, _, _ = analyze_sentiment(msg.content, is_mbras_user)
        sentiments_by_id[msg.msg_id] = label
        if label != "meta":
            sentiment_counts[label] += 1
            sentiment_total += 1

        sentiment_sequences.setdefault(msg.user_id, []).append((msg.timestamp, label))
        user_timestamps.setdefault(msg.user_id, []).append(msg.timestamp)
        all_timestamps.append(msg.timestamp)

        stats = user_stats.setdefault(
            msg.user_id,
            {"reactions": 0, "shares": 0, "views": 0, "mbras": is_mbras_user},
        )
        stats["reactions"] += msg.reactions
        stats["shares"] += msg.shares
        stats["views"] += msg.views
        stats["mbras"] = stats["mbras"] or is_mbras_user

        total_interactions += msg.reactions + msg.shares
        total_views += msg.views

    if sentiment_total == 0:
        sentiment_distribution = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    else:
        sentiment_distribution = {
            key: round((count / sentiment_total) * 100.0, 1)
            for key, count in sentiment_counts.items()
        }

    trending_topics = _compute_trending(filtered_messages, now_utc, sentiments_by_id)

    phi = (1 + math.sqrt(5)) / 2
    influence_ranking = []
    for user_id, stats in user_stats.items():
        followers = _followers_from_user_id(user_id)
        interactions = stats["reactions"] + stats["shares"]
        if stats["views"] > 0:
            engagement_rate = interactions / stats["views"]
        else:
            engagement_rate = 0.0
        if interactions > 0 and interactions % 7 == 0:
            engagement_rate *= (1 + (1 / phi))

        influence_score = (followers * 0.4) + (engagement_rate * 0.6)
        if user_id.lower().endswith("007"):
            influence_score *= 0.5
        if stats["mbras"]:
            influence_score += 2.0

        influence_ranking.append(
            {
                "user_id": user_id,
                "influence_score": round(influence_score, 4),
            }
        )

    influence_ranking.sort(
        key=lambda item: (-item["influence_score"], item["user_id"])
    )

    anomaly_type: Optional[str] = None
    if _detect_burst(user_timestamps):
        anomaly_type = "burst"
    elif _detect_alternating(sentiment_sequences):
        anomaly_type = "alternating_sentiment"
    elif _detect_synchronized(all_timestamps):
        anomaly_type = "synchronized_posting"

    if flags["candidate_awareness"]:
        engagement_score = 9.42
    else:
        engagement_score = (total_interactions / total_views) if total_views else 0.0

    return {
        "sentiment_distribution": sentiment_distribution,
        "engagement_score": engagement_score,
        "trending_topics": trending_topics,
        "influence_ranking": influence_ranking,
        "anomaly_detected": anomaly_type is not None,
        "anomaly_type": anomaly_type,
        "flags": flags,
    }
