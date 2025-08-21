import asyncio
from contextvars import ContextVar
from pathlib import Path

from astabench.tools.stateful_python import exec_python_session
from astabench.util.sandbox import SandboxJupyter

sandbox_jupyter = ContextVar[SandboxJupyter]("sandbox_jupyter")


def exec_python(code: str):
    """
    Execute python code and return the output or error message.

    Parameters
    ----------
    code (str): Python code to execute.

    Returns
    -------
    str: Output or error message.
    """
    return asyncio.run(exec_python_session(code))


def install_packages(packages: list[str], install_in_bulk: bool = False):
    """
    Install a list of packages using pip in the current Jupyter/IPython environment.

    Parameters:
    packages (list of str): Names of the packages to install.
    install_in_bulk (bool): (Default) If False, install each package individually.
                            Individual installation is useful for debugging purposes.
                            If True, install all packages in one subprocess call.
                            Useful to save time when installing multiple packages.
    """

    # tools.py defines `def install_packages`
    code = (Path(__file__).parent / "static" / "tools.py").read_text()

    code += "\n\n"

    code += (
        f"install_packages(packages={packages}, install_in_bulk={install_in_bulk})\n"
    )

    return exec_python(code)
