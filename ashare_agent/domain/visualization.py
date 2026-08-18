from decimal import Decimal
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class ResponseOutputMode(str, Enum):
    TEXT = "text"
    CHART = "chart"


class ChartType(str, Enum):
    LINE = "line"
    BAR = "bar"
    COMBO = "combo"


class ChartSeriesStyle(str, Enum):
    LINE = "line"
    BAR = "bar"


class ChartAxis(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class ChartSeries(BaseModel):
    name: str
    values: list[Decimal | None]
    unit: str
    style: ChartSeriesStyle
    axis: ChartAxis = ChartAxis.LEFT


class ChartSpec(BaseModel):
    chart_type: ChartType
    title: str
    x_labels: list[str]
    series: list[ChartSeries] = Field(min_length=1)
    x_label: str = "年度"
    left_y_label: str | None = None
    right_y_label: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_series_lengths(self):
        expected_length = len(self.x_labels)

        if expected_length == 0:
            raise ValueError("Chart x_labels cannot be empty")

        for item in self.series:
            if len(item.values) != expected_length:
                raise ValueError("Chart series length must match x_labels length")

        return self


class ChartArtifact(BaseModel):
    artifact_id: str
    file_path: Path
    mime_type: str = "image/png"
    title: str
    width: int
    height: int
    chart_type: ChartType
