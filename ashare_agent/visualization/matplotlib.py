import asyncio
from hashlib import sha256
from pathlib import Path
import tempfile

from ashare_agent.domain import (
    ChartArtifact,
    ChartAxis,
    ChartSeriesStyle,
    ChartSpec,
)


class MatplotlibChartRenderer:
    def __init__(
        self,
        output_directory: str | Path,
        *,
        font_family: str = "AR PL UKai CN",
        width: int = 1200,
        height: int = 720,
        dpi: int = 100,
    ):
        self._output_directory = Path(output_directory).expanduser()
        self._font_family = font_family
        self._width = width
        self._height = height
        self._dpi = dpi

    async def render(
        self,
        spec: ChartSpec,
    ) -> ChartArtifact:
        return await asyncio.to_thread(
            self._render_sync,
            spec,
        )

    def _render_sync(
        self,
        spec: ChartSpec,
    ) -> ChartArtifact:
        from matplotlib import font_manager
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.ticker import FuncFormatter

        artifact_id = sha256(spec.model_dump_json().encode("utf-8")).hexdigest()[:20]
        output_path = self._output_directory / f"financial-chart-{artifact_id}.png"

        self._output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        font = _resolve_font(
            font_manager,
            self._font_family,
        )
        figure = Figure(
            figsize=(
                self._width / self._dpi,
                self._height / self._dpi,
            ),
            dpi=self._dpi,
            facecolor="#F8FAFC",
        )
        FigureCanvasAgg(figure)
        axis_left = figure.add_subplot(111)
        axis_left.set_facecolor("#FFFFFF")
        axis_left.yaxis.set_major_formatter(FuncFormatter(_format_tick))
        axis_right = None
        x_positions = list(range(len(spec.x_labels)))
        handles = []
        labels = []

        for index, item in enumerate(spec.series):
            axis = axis_left

            if item.axis == ChartAxis.RIGHT:
                if axis_right is None:
                    axis_right = axis_left.twinx()
                    axis_right.yaxis.set_major_formatter(FuncFormatter(_format_tick))

                axis = axis_right

            values = [
                float(value) if value is not None else float("nan")
                for value in item.values
            ]

            if item.style == ChartSeriesStyle.BAR:
                bars = axis.bar(
                    x_positions,
                    values,
                    width=0.58,
                    color="#2563EB",
                    alpha=0.84,
                    label=item.name,
                    zorder=2,
                )
                handles.append(bars)
                labels.append(item.name)
                _annotate_bars(
                    axis,
                    bars,
                    item.values,
                    font,
                )
            else:
                line = axis.plot(
                    x_positions,
                    values,
                    color=("#DC2626" if item.axis == ChartAxis.RIGHT else "#2563EB"),
                    linewidth=2.4,
                    marker="o",
                    markersize=6,
                    label=item.name,
                    zorder=3,
                )[0]
                handles.append(line)
                labels.append(item.name)
                _annotate_line(
                    axis,
                    x_positions,
                    item.values,
                    item.unit,
                    font,
                )

        axis_left.set_xticks(
            x_positions,
            spec.x_labels,
            fontproperties=font,
        )
        axis_left.set_xlabel(
            spec.x_label,
            fontproperties=font,
        )

        if spec.left_y_label:
            axis_left.set_ylabel(
                spec.left_y_label,
                fontproperties=font,
                color="#1D4ED8",
            )

        if axis_right is not None and spec.right_y_label:
            axis_right.set_ylabel(
                spec.right_y_label,
                fontproperties=font,
                color="#B91C1C",
            )

        axis_left.set_title(
            spec.title,
            fontproperties=font,
            fontsize=18,
            pad=18,
        )
        axis_left.grid(
            axis="y",
            color="#CBD5E1",
            linewidth=0.8,
            alpha=0.65,
            zorder=0,
        )
        axis_left.margins(y=0.14)
        axis_left.axhline(
            0,
            color="#64748B",
            linewidth=0.8,
            zorder=1,
        )

        if axis_right is not None:
            axis_right.margins(y=0.20)
            axis_right.axhline(
                0,
                color="#DC2626",
                linewidth=0.7,
                alpha=0.35,
                zorder=1,
            )

        axis_left.legend(
            handles,
            labels,
            loc="upper left",
            prop=font,
            frameon=False,
        )
        _style_axis(axis_left, font)

        if axis_right is not None:
            _style_axis(axis_right, font)

        if spec.notes:
            figure.text(
                0.5,
                0.02,
                "  ｜  ".join(spec.notes),
                ha="center",
                va="bottom",
                fontproperties=font,
                fontsize=10,
                color="#475569",
            )

        figure.subplots_adjust(
            left=0.10,
            right=0.90 if axis_right is not None else 0.96,
            top=0.88,
            bottom=0.16 if spec.notes else 0.12,
        )

        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                dir=self._output_directory,
                prefix=f".{artifact_id}-",
                suffix=".png",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)

            figure.savefig(
                temporary_path,
                format="png",
                dpi=self._dpi,
                facecolor=figure.get_facecolor(),
            )
            temporary_path.replace(output_path)
        finally:
            figure.clear()

            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        return ChartArtifact(
            artifact_id=artifact_id,
            file_path=output_path.resolve(),
            title=spec.title,
            width=self._width,
            height=self._height,
            chart_type=spec.chart_type,
        )


def _resolve_font(
    font_manager,
    preferred_family: str,
):
    try:
        path = font_manager.findfont(
            preferred_family,
            fallback_to_default=False,
        )
    except ValueError:
        path = font_manager.findfont("DejaVu Sans")

    return font_manager.FontProperties(fname=path)


def _style_axis(axis, font) -> None:
    axis.tick_params(colors="#475569")

    for label in axis.get_xticklabels() + axis.get_yticklabels():
        label.set_fontproperties(font)

    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#CBD5E1")
    axis.spines["bottom"].set_color("#CBD5E1")


def _annotate_bars(
    axis,
    bars,
    values,
    font,
) -> None:
    for bar, value in zip(bars, values):
        if value is None:
            continue

        height = float(value)
        offset = 4 if height >= 0 else -13
        vertical_alignment = "bottom" if height >= 0 else "top"
        axis.annotate(
            _compact_number(value),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, offset),
            textcoords="offset points",
            ha="center",
            va=vertical_alignment,
            fontproperties=font,
            fontsize=9,
            color="#1E3A8A",
        )


def _annotate_line(
    axis,
    x_positions,
    values,
    unit: str,
    font,
) -> None:
    for x_position, value in zip(x_positions, values):
        if value is None:
            continue

        axis.annotate(
            f"{_compact_number(value)}{unit}",
            xy=(x_position, float(value)),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontproperties=font,
            fontsize=9,
            color="#991B1B",
        )


def _compact_number(value) -> str:
    text = format(value, ".2f")
    return text.rstrip("0").rstrip(".")


def _format_tick(value, _position) -> str:
    return f"{value:g}"
