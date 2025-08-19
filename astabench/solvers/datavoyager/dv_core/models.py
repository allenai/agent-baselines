from typing import Union
from pydantic import BaseModel


class ExecutePython(BaseModel):
    code: str


class InstallPackages(BaseModel):
    packages: list[str]
    install_in_bulk: bool = False


class ToolCall(BaseModel):
    tool: Union[ExecutePython, InstallPackages]
