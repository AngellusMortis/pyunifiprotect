from distutils.core import setup
import setuptools  # noqa

setup(
    name="pyunifiprotect",
    packages=["pyunifiprotect"],
    version="0.31.8",
    license="MIT",
    description="Python Wrapper for Unifi Protect API",
    author="Bjarne Riis",
    author_email="bjarne@briis.com",
    url="https://github.com/briis/pyunifiprotect",
    keywords=["UnifiProtect", "Surveilance", "Unifi", "Home Assistant", "Python"],
    install_requires=[
        "aiohttp",
        "asyncio",
        "pyjwt",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",  # Chose either "3 - Alpha", "4 - Beta" or "5 - Production/Stable" as the current state of your package
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
)
