import json

from pydantic import BaseModel

from ashare_agent.domain import ChartArtifact


def to_data(value):
    if isinstance(value, ChartArtifact):
        return {
            "artifact_id": value.artifact_id,
            "mime_type": value.mime_type,
            "title": value.title,
            "width": value.width,
            "height": value.height,
            "chart_type": value.chart_type.value,
        }

    if isinstance(value, BaseModel):
        return {
            field_name: to_data(getattr(value, field_name))
            for field_name in type(value).model_fields
        }

    if isinstance(value, list):
        return [to_data(item) for item in value]

    if isinstance(value, tuple):
        return [to_data(item) for item in value]

    if isinstance(value, dict):
        return {key: to_data(item) for key, item in value.items()}

    return value


def dumps(value) -> str:
    return json.dumps(
        to_data(value),
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def message_to_text(message) -> str:
    content = getattr(
        message,
        "content",
        message,
    )

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []

        for item in content:
            if isinstance(item, str):
                texts.append(item)

            elif isinstance(item, dict):
                text = item.get("text")

                if text:
                    texts.append(text)

        return "\n".join(texts)

    return str(content)
