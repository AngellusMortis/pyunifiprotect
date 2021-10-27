import os

from dotenv import load_dotenv

from pyunifiprotect.cli import app


def start():
    env_file = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_file):
        load_dotenv(dotenv_path=env_file)
    else:
        load_dotenv()
    app()


if __name__ == "__main__":
    start()
