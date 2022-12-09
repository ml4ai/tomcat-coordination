from typing import List

import argparse
import os
import pickle

from coordination.model.beta_coordination_blending_latent_vocalics import BetaCoordinationBlendingLatentVocalics
from coordination.model.utils.beta_coordination_blending_latent_vocalics import BetaCoordinationLatentVocalicsDataset


def infer(model_path: str, dataset_path: str, num_particles: int, seed: int, num_jobs: int, out_dir: str,
          features: List[str], gendered: bool):

    # Loading dataset
    with open(dataset_path, "rb") as f:
        dataset = BetaCoordinationLatentVocalicsDataset.from_latent_vocalics_dataset(pickle.load(f))

    FEATURE_MAP = {
        "pitch": 0,
        "intensity": 1,
        "jitter": 2,
        "shimmer": 3,
    }
    dataset.keep_features([FEATURE_MAP[f] for f in features])

    if gendered:
        raise NotImplementedError
    else:
        model = BetaCoordinationBlendingLatentVocalics.from_pickled_file(model_path)
        dataset.normalize_per_subject()

    summaries = model.predict(evidence=dataset, num_particles=num_particles, seed=seed, num_jobs=num_jobs)

    os.makedirs(out_dir, exist_ok=True)

    with open(f"{out_dir}/inference_summaries.pkl", "wb") as f:
        pickle.dump(summaries, f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Infers coordination given a trained model and a dataset of observed vocalics over time."
    )

    parser.add_argument("--model_path", type=str, required=True,
                        help="Path to a pre-trained coordination model.")
    parser.add_argument("--dataset_path", type=str, required=True,
                        help="Path to the dataset used to train the coordination model.")
    parser.add_argument("--n_particles", type=int, required=False, default=10000,
                        help="Number of particles used for inference.")
    parser.add_argument("--seed", type=int, required=False, default=0, help="Random seed for replication.")
    parser.add_argument("--n_jobs", type=int, required=False, default=1,
                        help="Number of jobs to infer trials in parallel.")
    parser.add_argument("--out_dir", type=str, required=True, help="Directory where to save the inferences.")
    parser.add_argument("--features", type=str, required=False, default="pitch, intensity, jitter, shimmer",
                        help="List of vocalic features to consider. It can be any subset of the default value.",)
    parser.add_argument("--gendered", action="store_true", required=False, default=False,
                        help="Whether to use a model that considers speakers' genders.")

    args = parser.parse_args()

    infer(model_path=args.model_path,
          dataset_path=args.dataset_path,
          num_particles=args.n_particles,
          seed=args.seed,
          num_jobs=args.n_jobs,
          out_dir=args.out_dir,
          features=list(map(str.strip, args.features.split(","))),
          gendered=args.gendered)
