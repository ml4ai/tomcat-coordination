from typing import Optional

import argparse
from glob import glob
import re
import os

from coordination.common.log import configure_log
from coordination.config.database_config import DatabaseConfig
from coordination.entity.trial import Trial
from coordination.loader.vocalics_reader import VocalicFeature, VocalicsReader
from coordination.loader.vocalics_reader_csv import VocalicsReaderCSV
from coordination.loader.vocalics_reader_db import VocalicsReaderDB


def serialize_single_trial(metadata_filepath: str, out_dir: str, verbose: bool, log_dir: str,
                           vocalics_reader: VocalicsReader, overwrite: bool):
    if os.path.exists(out_dir):
        out_filepaths = set([dir_path.rsplit("/", 1)[-1] for dir_path in os.listdir(out_dir)])
    else:
        out_filepaths = []
    trial_number = re.match(R".*(T000\d+).*", metadata_filepath).group(1)
    if not overwrite and trial_number in out_filepaths:
        print(f"Skipping {trial_number}. Serialized version found in {out_dir}.")
    else:
        log_filepath = ""
        if log_dir != "":
            filename = os.path.basename(metadata_filepath).rsplit('.')[0]
            log_filepath = f"{log_dir}/{filename}.txt"

        configure_log(verbose, log_filepath)
        trial = Trial.from_metadata_file(metadata_filepath, vocalics_reader)
        trial.save(out_dir)


def serialize_trials(input_path: str, out_dir: str, verbose: bool, log_dir: str,
                     vocalics_source: str, database_config: DatabaseConfig, vocalics_dir: Optional[str], multi: bool,
                     overwrite: bool):
    if not os.path.exists(input_path):
        raise Exception(f"Directory {input_path} does not exist.")

    vocalic_features = [VocalicFeature.PITCH, VocalicFeature.INTENSITY]
    if vocalics_source == "csv":
        vocalics_reader = VocalicsReaderCSV(vocalics_dir, vocalic_features)
    elif vocalics_source == "db":
        vocalics_reader = VocalicsReaderDB(database_config, vocalic_features)
    else:
        raise Exception(f"Invalid source {vocalics_source} for vocalics.")

    if multi:
        filepaths = glob(f"{input_path}/*.metadata")
        for i, filepath in enumerate(filepaths):
            # I print the progress to the screen because progress bars are used internally for each metadata file
            # and nested progress bars do not work well.
            if i > 0:
                print("")

            print(f"[{i + 1}/{len(filepaths)}]: {os.path.basename(filepath)}")
            serialize_single_trial(filepath, out_dir, verbose, log_dir, vocalics_reader, overwrite)
    else:
        serialize_single_trial(input_path, out_dir, verbose, log_dir, vocalics_reader, overwrite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parses a Minecraft .metadata file to extract relevant data to the coordination model and "
                    "saves the post processed trial structures to a folder."
    )

    parser.add_argument("--input_path", type=str, required=True,
                        help="Path to the .metadata file to be parsed or directory containing a list of .metadata "
                             "files if the multi option is enabled.")
    parser.add_argument("--out_dir", type=str, required=True,
                        help="Directory directory with serialized trial must be saved.")
    parser.add_argument("--verbose", action="store_true", required=False, default=False,
                        help="Whether to print the logs.")
    parser.add_argument("--log_dir", type=str, required=False,
                        help="Directory where log files must be saved. If not provided, logs will be printed to the "
                             "terminal if the --verbose option is active.")
    parser.add_argument("--vocalics_database_address", type=str, required=False, default="localhost",
                        help="Address of the database server containing the vocalic features.")
    parser.add_argument("--vocalics_database_port", type=int, required=False, default=5432,
                        help="Port of the database server containing the vocalic features.")
    parser.add_argument("--vocalics_database_name", type=str, required=False, default="asist_vocalics",
                        help="Name of the database containing the vocalic features.")
    parser.add_argument("--vocalics_csv_dir", type=str, required=False,
                        help="Directory containing a list of trial directories in which .csv files"
                             "containing vocalic features are located.")
    parser.add_argument("--multi", action="store_true", required=False, default=False,
                        help="Whether input_path is a directory with a list of .metadata files to be processed.")
    parser.add_argument("--overwrite", action="store_true", required=False, default=False,
                        help="Whether to overwrite an already serialized trial.")
    parser.add_argument("--vocalics_src", type=str, required=True, default="csv", choices=["csv", "db"],
                        help="Where to load vocalics from.")

    args = parser.parse_args()
    database_config = DatabaseConfig(args.vocalics_database_address, args.vocalics_database_port,
                                     args.vocalics_database_name)
    serialize_trials(args.input_path, args.out_dir, args.verbose, args.log_dir, args.vocalics_src, database_config,
                     args.vocalics_csv_dir, args.multi, args.overwrite)
