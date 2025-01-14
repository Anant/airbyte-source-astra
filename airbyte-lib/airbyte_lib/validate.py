# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
"""Defines the `airbyte-lib-validate-source` CLI, which checks if connectors are compatible with airbyte-lib."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

import airbyte_lib as ab
import yaml


def _parse_args():
    parser = argparse.ArgumentParser(description="Validate a connector")
    parser.add_argument(
        "--connector-dir",
        type=str,
        required=True,
        help="Path to the connector directory",
    )
    parser.add_argument(
        "--sample-config",
        type=str,
        required=True,
        help="Path to the sample config.json file",
    )
    return parser.parse_args()


def _run_subprocess_and_raise_on_failure(args: List[str]):
    result = subprocess.run(args)
    if result.returncode != 0:
        raise Exception(f"{args} exited with code {result.returncode}")


def tests(connector_name, sample_config):
    print("Creating source and validating spec and version...")
    source = ab.get_connector(connector_name, config=json.load(open(sample_config)))

    print("Running check...")
    source.check()

    print("Fetching streams...")
    streams = source.get_available_streams()

    # try to peek all streams - if one works, stop, if none works, throw exception
    for stream in streams:
        try:
            print(f"Trying to read from stream {stream}...")
            record = next(source.read_stream(stream))
            assert record, "No record returned"
            break
        except Exception as e:
            print(f"Could not read from stream {stream}: {e}")
    else:
        raise Exception(f"Could not read from any stream from {streams}")


def run():
    """
    This is a CLI entrypoint for the `airbyte-lib-validate-source` command.
    It's called like this: airbyte-lib-validate-source —connector-dir . -—sample-config secrets/config.json
    It performs a basic smoke test to make sure the connector in question is airbyte-lib compliant:
    * Can be installed into a venv
    * Can be called via cli entrypoint
    * Answers according to the Airbyte protocol when called with spec, check, discover and read
    """

    # parse args
    args = _parse_args()
    connector_dir = args.connector_dir
    sample_config = args.sample_config
    validate(connector_dir, sample_config)


def validate(connector_dir, sample_config):
    # read metadata.yaml
    metadata_path = Path(connector_dir) / "metadata.yaml"
    with open(metadata_path, "r") as stream:
        metadata = yaml.safe_load(stream)["data"]

    # TODO: Use remoteRegistries.pypi.packageName once set for connectors
    connector_name = metadata["dockerRepository"].replace("airbyte/", "")

    # create a venv and install the connector
    venv_name = f".venv-{connector_name}"
    venv_path = Path(venv_name)
    if not venv_path.exists():
        _run_subprocess_and_raise_on_failure([sys.executable, "-m", "venv", venv_name])

    pip_path = os.path.join(venv_name, "bin", "pip")

    _run_subprocess_and_raise_on_failure([pip_path, "install", "-e", connector_dir])

    # write basic registry to temp json file
    registry = {
        "sources": [
            {
                "dockerRepository": f"airbyte/{connector_name}",
                "dockerImageTag": "0.0.1",
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode="w+t", delete=True) as temp_file:
        temp_file.write(json.dumps(registry))
        temp_file.seek(0)
        os.environ["AIRBYTE_LOCAL_REGISTRY"] = str(temp_file.name)
        tests(connector_name, sample_config)
