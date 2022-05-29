from dataclasses import dataclass

from pyunifiprotect.api import ProtectApiClient


@dataclass
class CliContext:
    protect: ProtectApiClient
