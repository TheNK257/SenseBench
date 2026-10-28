"""`sensebench` command line."""

from pathlib import Path

import typer

from sensebench import __version__

app = typer.Typer(
    help="SenseBench: telemetry viewer and alert engine for recorded runs.",
    no_args_is_help=True,
)


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Bind address (default 127.0.0.1)."),
    port: int | None = typer.Option(None, help="Port (default 8000)."),
    data_dir: Path | None = typer.Option(None, help="Session data directory (default ./data)."),
) -> None:
    """Run the SenseBench server (one process; no database server needed)."""
    import uvicorn

    from sensebench.api import create_app
    from sensebench.config import Settings

    overrides = {"host": host, "port": port, "data_dir": data_dir}
    settings = Settings(**{k: v for k, v in overrides.items() if v is not None})
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


@app.command()
def synth(
    out_dir: Path = typer.Argument(..., help="Directory to write run.csv and ground_truth.json."),
    duration: float = typer.Option(600.0, help="Run length in seconds (minimum 300)."),
    rate: int = typer.Option(100, help="Fast-signal sample rate in Hz (multiple of 10)."),
    seed: int = typer.Option(0, help="Random seed; same seed gives an identical run."),
) -> None:
    """Generate a synthetic Formula-Student-style run with known injected faults."""
    from sensebench.synthetic import generate

    run = generate(duration_s=duration, rate_hz=rate, seed=seed)
    csv_path, gt_path = run.write(out_dir)
    typer.echo(f"wrote {csv_path} ({run.time_s.size} rows) and {gt_path}")
    for fault in run.faults:
        typer.echo(f"  {fault.kind:<16} {fault.start_s:8.2f} - {fault.end_s:8.2f} s")


@app.command()
def version() -> None:
    """Print the SenseBench version."""
    typer.echo(__version__)
