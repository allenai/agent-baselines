import json
import logging

from autogen_agentchat.base import TaskResult
from autogen_core.models._types import FunctionCall, FunctionExecutionResult
from termcolor import colored


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger_name": record.name,
            "module": record.module,
            "function": record.funcName,
            "message": record.getMessage(),
        }
        return json.dumps(log_data)


class DVLogger:
    def __init__(
        self,
        logger_name: str,
        log_filename: str = None,
        use_json_formatter: bool = True,
    ) -> None:
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        if log_filename:
            # If log_filename is provided, log to a file
            self.file_handler = logging.FileHandler(log_filename)
            self.file_handler.setLevel(logging.INFO)
            if use_json_formatter:
                self.json_formatter = JSONFormatter()
                self.file_handler.setFormatter(self.json_formatter)
            self.logger.addHandler(self.file_handler)
        else:
            # If log_filename is not provided, log to the console
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            if use_json_formatter:
                self.json_formatter = JSONFormatter()
                console_handler.setFormatter(self.json_formatter)
            self.logger.addHandler(console_handler)

    # To log string
    def log(self, message: str) -> None:
        self.logger.info(message)

    # To log dictionary (agent reponse)
    def log_json(self, message) -> None:
        self.logger.info(json.dumps(message))


def tool_call_formatter(obj):
    if obj is None or isinstance(obj, (str, int, float, bool, dict)):
        return obj

    # NOTE: FunctionExecutionResult is marked as deprecated
    # inside autogen, so we might need to remove this in future
    result = ""
    if isinstance(obj, FunctionExecutionResult):
        result += f"\n**Call ID: {obj.call_id}**\n\n"
        result += "\n```\n"
        result += obj.content
        result += "\n```\n"
        result += "\n"

    if isinstance(obj, FunctionCall):
        code_snippet = json.loads(obj.arguments)
        result += f"**Function: {obj.name}**\n"
        result += "\n```python\n"
        try:
            result += code_snippet["code"]
        except KeyError:
            result += str(code_snippet)
        result += "\n```\n"
        result += "\n"

    return result


def log_to_markdown_file(logger, message):
    if isinstance(message, TaskResult):
        logger.log("> [!NOTE]")
        logger.log("> ### Finish Reason")
        logger.log("")
        logger.log(f"{message.stop_reason}")
    else:
        logger.log("> [!NOTE]")
        logger.log(f"> ### {message.source}")
        logger.log("")

        def parse(content):
            if isinstance(content, str):
                logger.log(content)
            else:
                message = tool_call_formatter(content)
                logger.log(message)

        if isinstance(message.content, list):
            for c in message.content:
                parse(c)
        elif isinstance(message.content, str):
            logger.log(message.content)
        else:
            parse(message.content)

        logger.log("")
        logger.log("")


def log_to_json_file(logger, message):
    if isinstance(message, TaskResult):
        logger.log_json({"Finish Reason": message.stop_reason})
    else:

        def parse(content):
            if isinstance(content, str):
                logger.log_json(content)
            else:
                message = tool_call_formatter(content)
                logger.log_json(message)

        if isinstance(message.content, list):
            for c in message.content:
                parse(c)
        elif isinstance(message.content, str):
            logger.log_json(message.content)
        else:
            parse(message.content)


def log_to_console(logger, message):
    if isinstance(message, TaskResult):
        logger.log(colored("=" * 50, "blue"))
        logger.log(colored(message.stop_reason, "red"))
    else:
        logger.log(colored("=" * 50, "blue"))
        logger.log(colored(message.source, "green"))

        def parse(content):
            if isinstance(content, str):
                logger.log(content)
            else:
                message = tool_call_formatter(content)
                logger.log(message)

        if isinstance(message.content, list):
            for c in message.content:
                parse(c)
        elif isinstance(message.content, str):
            logger.log(message.content)
        else:
            parse(message.content)

        logger.log("")
        logger.log("")
