"""Offline startup compatibility checks for packaged runtime components."""
from prompt_toolkit.application import Application
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.input import DummyInput

from hund.learning.commit_controller import CommitController
from hund.skills.vault import SkillVault
from hund.ui.layout_factory import create_tui_layout


def test_tui_layout_and_runtime_components_construct(tmp_path):
    layout = create_tui_layout()
    app = Application(
        layout=layout,
        input=DummyInput(),
        output=DummyOutput(),
        full_screen=True,
    )
    assert app.layout is layout
    assert SkillVault(home=tmp_path).get_active_skills() == []
    controller = CommitController(home=tmp_path, db_path=tmp_path / "knowledge.db")
    assert controller.home == tmp_path


def test_fullscreen_module_imports_against_installed_prompt_toolkit():
    from hund.ui.fullscreen import run_fullscreen
    assert callable(run_fullscreen)

