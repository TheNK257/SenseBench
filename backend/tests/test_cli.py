from typer.testing import CliRunner

from sensebench import __version__
from sensebench.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_synth_writes_run_and_ground_truth(tmp_path):
    result = runner.invoke(app, ["synth", str(tmp_path), "--duration", "300", "--seed", "3"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "run.csv").is_file()
    assert (tmp_path / "ground_truth.json").is_file()
    assert "overheat" in result.stdout
