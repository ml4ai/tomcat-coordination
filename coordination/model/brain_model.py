from __future__ import annotations
from typing import Any, Optional, Tuple

import arviz as az
import numpy as np
import pymc as pm
import xarray

from coordination.model.components.coordination_component import SigmoidGaussianCoordinationComponent, \
    SigmoidGaussianCoordinationComponentSamples
from coordination.model.components.mixture_component import MixtureComponent, MixtureComponentSamples
from coordination.model.components.observation_component import ObservationComponent, ObservationComponentSamples

from coordination.common.functions import sigmoid


class BrainSamples:

    def __init__(self, coordination: SigmoidGaussianCoordinationComponentSamples, latent_brain: MixtureComponentSamples,
                 obs_brain: ObservationComponentSamples):
        self.coordination = coordination
        self.latent_brain = latent_brain
        self.obs_brain = obs_brain


class BrainSeries:

    def __init__(self, num_time_steps_in_coordination_scale: int, obs_brain: np.ndarray,
                 brain_time_steps_in_coordination_scale: np.ndarray):
        self.num_time_steps_in_coordination_scale = num_time_steps_in_coordination_scale
        self.obs_brain = obs_brain
        self.brain_time_steps_in_coordination_scale = brain_time_steps_in_coordination_scale

    @property
    def num_time_steps_in_brain_scale(self) -> int:
        return self.obs_brain.shape[-1]

    @property
    def num_brain_channels(self) -> int:
        return self.obs_brain.shape[-2]

    @property
    def num_subjects(self) -> int:
        return self.obs_brain.shape[-3]


class BrainPosteriorSamples:

    def __init__(self, unbounded_coordination: xarray.Dataset, coordination: xarray.Dataset,
                 latent_brain: xarray.Dataset):
        self.unbounded_coordination = unbounded_coordination
        self.coordination = coordination
        self.latent_brain = latent_brain

    @classmethod
    def from_inference_data(cls, idata: Any) -> BrainPosteriorSamples:
        unbounded_coordination = idata.posterior["unbounded_coordination"]
        coordination = sigmoid(unbounded_coordination)
        latent_brain = idata.posterior["latent_brain"]

        return cls(unbounded_coordination, coordination, latent_brain)


class BrainModel:

    def __init__(self, initial_coordination: float, num_subjects: int, num_brain_channels: int,
                 self_dependent: bool, sd_uc: float, sd_mean_a0: np.ndarray, sd_sd_aa: np.ndarray,
                 sd_sd_o: np.ndarray, a_mixture_weights: np.ndarray):
        self.num_subjects = num_subjects
        self.num_brain_channels = num_brain_channels

        self.hyper_parameters = {
            "num_subjects": num_subjects,
            "num_brain_channels": num_brain_channels,
            "self_dependent": self_dependent,
            "sd_uc": sd_uc,
            "sd_mean_a0": sd_mean_a0.tolist(),
            "sd_sd_aa": sd_sd_aa.tolist(),
            "sd_sd_o": sd_sd_o.tolist(),
            "a_mixture_weights": a_mixture_weights.tolist()
        }

        self.coordination_cpn = SigmoidGaussianCoordinationComponent(initial_coordination, sd_uc=sd_uc)
        self.latent_brain_cpn = MixtureComponent("latent_brain", num_subjects, num_brain_channels, self_dependent,
                                                 sd_mean_a0=sd_mean_a0, sd_sd_aa=sd_sd_aa,
                                                 a_mixture_weights=a_mixture_weights)
        self.obs_brain_cpn = ObservationComponent("obs_brain", num_subjects, num_brain_channels, sd_sd_o=sd_sd_o)

    def draw_samples(self, num_series: int, num_time_steps: int, seed: Optional[int],
                     brain_relative_frequency: float) -> BrainSamples:
        coordination_samples = self.coordination_cpn.draw_samples(num_series, num_time_steps, seed)
        latent_brain_samples = self.latent_brain_cpn.draw_samples(num_series,
                                                                  relative_frequency=brain_relative_frequency,
                                                                  coordination=coordination_samples.coordination)
        obs_brain_samples = self.obs_brain_cpn.draw_samples(latent_component=latent_brain_samples.values)

        samples = BrainSamples(coordination_samples, latent_brain_samples, obs_brain_samples)

        return samples

    def fit(self, evidence: BrainSeries, burn_in: int, num_samples: int, num_chains: int,
            seed: Optional[int] = None, num_jobs: int = 1) -> Tuple[pm.Model, az.InferenceData]:
        assert evidence.num_subjects == self.num_subjects
        assert evidence.num_brain_channels == self.num_brain_channels

        pymc_model = self._define_pymc_model(evidence)
        with pymc_model:
            idata = pm.sample(num_samples, init="jitter+adapt_diag", tune=burn_in, chains=num_chains, random_seed=seed,
                              cores=num_jobs)

        return pymc_model, idata

    def _define_pymc_model(self, evidence: BrainSeries):
        coords = {"subject": np.arange(self.num_subjects),
                  "brain_channel": np.arange(self.num_brain_channels),
                  "coordination_time": np.arange(evidence.num_time_steps_in_coordination_scale),
                  "brain_time": np.arange(evidence.num_time_steps_in_brain_scale)}

        pymc_model = pm.Model(coords=coords)
        with pymc_model:
            _, coordination, _ = self.coordination_cpn.update_pymc_model(time_dimension="coordination_time")
            latent_brain, _, _, _ = self.latent_brain_cpn.update_pymc_model(
                coordination=coordination[evidence.brain_time_steps_in_coordination_scale],
                subject_dimension="subject",
                time_dimension="brain_time",
                feature_dimension="brain_channel")
            self.obs_brain_cpn.update_pymc_model(latent_component=latent_brain, observed_values=evidence.obs_brain)

        return pymc_model

    def prior_predictive(self, evidence: BrainSeries, seed: Optional[int] = None):
        pymc_model = self._define_pymc_model(evidence)
        with pymc_model:
            idata = pm.sample_prior_predictive(random_seed=seed)

        return pymc_model, idata

    def clear_parameter_values(self):
        self.coordination_cpn.parameters.clear_values()
        self.latent_brain_cpn.parameters.clear_values()
        self.obs_brain_cpn.parameters.clear_values()
