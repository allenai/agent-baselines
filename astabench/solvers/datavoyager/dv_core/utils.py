import re
import sys
from io import StringIO

from IPython import get_ipython
from IPython.core.interactiveshell import InteractiveShell


class DataVoyagerShell:
    """
    Singleton class to access the IPython shell in Jupyter notebook or
    the InteractiveShell instance in the IPython environment.

    Attributes
    ----------
    shell: InteractiveShell or IPython shell instance.

    Methods
    -------
    is_jupyter_notebook_env()
        Check if the current environment is Jupyter notebook.
    inject_tool(tool_name, tool_instance)
        Inject a tool instance into the IPython shell.
    """

    _instance = None

    def __new__(cls):
        """
        Create a new instance of the class if it does not exist.

        Returns
        -------
        DataVoyagerShell: Instance of the class.
        """
        if not cls._instance:
            cls._instance = super(DataVoyagerShell, cls).__new__(cls)
            cls._instance._initialize_shell()
        return cls._instance

    def _initialize_shell(self):
        """
        Initialize the IPython shell or InteractiveShell instance.

        Returns
        -------
        None
        """
        if self.is_jupyter_notebook_env():
            self.shell = get_ipython()
        else:
            self.shell = InteractiveShell.instance()

    def is_jupyter_notebook_env(self):
        """
        Check if the current environment is Jupyter notebook.

        Returns
        -------
        bool: True if the current environment is Jupyter notebook, False otherwise.
        """
        # Check if IPython is available and
        # running in a notebook environment
        if "ipykernel" in sys.modules:
            return True
        return False

    def inject_tool(self, tool_name: str, tool: object):
        """
        Inject a tool instance into the IPython shell.

        Parameters
        ----------
        tool_name (str): Name of the tool.
        tool (object): Any object to inject in the shell.

        Returns
        -------
        None
        """
        self.shell.user_ns[tool_name] = tool


def remove_ansi_escape_sequences(text: str) -> str:
    """
    Removes ANSI escape sequences from the given text.

    Parameters
    ----------
    text (str): Text with ANSI escape sequences.

    Returns
    -------
    str: Text without ANSI escape sequences
    """
    # 7-bit C1 ANSI sequences
    ansi_escape = re.compile(
        r"""
        \x1B  # ESC
        (?:   # 7-bit C1 Fe (except CSI)
            [@-Z\\-_]
        |     # or [ for CSI, followed by a control sequence
            \[
            [0-?]*  # Parameter bytes
            [ -/]*  # Intermediate bytes
            [@-~]   # Final byte
        )
    """,
        re.VERBOSE,
    )
    return ansi_escape.sub("", text)


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
    output_buffer = StringIO()
    old_stdout = sys.stdout
    sys.stdout = output_buffer

    shell = DataVoyagerShell().shell

    try:
        result = shell.run_cell(code)
        output = output_buffer.getvalue()
        output = remove_ansi_escape_sequences(output)

        if result.success:
            log = f"Execution successful. Output:\n{output}"
        else:
            error_message = result.error_in_exec
            log = f"Error during execution:\n{error_message}"
            if len(output.splitlines()) < 20:
                log += f"\nTraceback:\n{output}"
            else:
                last_traceback = "\n".join(output.splitlines()[-20:])
                log += f"\nTraceback:\n{last_traceback}"

    except Exception as e:
        log = f"Error during execution:\n{str(e)}"

    finally:
        sys.stdout = old_stdout

    log = remove_ansi_escape_sequences(log)

    return log


def main():
    test_code = """
    def add(a, b):
        return a + b

    add(1, 2)
    """

    print(exec_python(test_code))

    test_code_with_error = """
    def add(a, b):
        return a + b

    add(1, '2')
    """

    print(exec_python(test_code_with_error))


if __name__ == "__main__":
    main()
